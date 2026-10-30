"""
User uploads: file -> text -> windows -> (scripted) LLM extraction -> corpus,
index, safety. Offline: the model is FakeLLM, files are built in the test.
"""
import json
from types import SimpleNamespace

import pytest

from pantry import config, corpus, matching, retriever, safety, uploads

LEMON_CAKE = {
    "title": "Grandma's Lemon Drizzle Cake",
    "description": "A tangy loaf cake.",
    "cuisine": "British",
    "dietary_tags": ["vegetarian"],
    "yield": {"amount": 8, "unit": "slices"},
    "prep_minutes": 15, "cook_minutes": 45, "rest_minutes": None, "oven_c": 180,
    "ingredients": [{"item": "self-raising flour", "qty": 225, "unit": "g"},
                    {"item": "unsalted butter", "qty": 225, "unit": "g"},
                    {"item": "eggs", "qty": 4, "unit": "piece"},
                    {"item": "lemon zest", "qty": None, "unit": "from 2 lemons"}],
    "method": ["Cream the butter and sugar.", "Beat in the eggs and flour.", "Bake 45 minutes."],
    "notes": "Drizzle while warm.",
    "safety_category": None,
}
SOURCE_TEXT = ("Grandma's Lemon Drizzle Cake\n\nIngredients\n225 g self-raising flour\n225 g butter\n4 eggs\n\n"
               "Method\n1. Cream the butter and sugar.\n2. Beat in the eggs and flour.\n3. Bake 45 minutes.")


def reply(*recipes, raw=None):
    return SimpleNamespace(content=raw if raw is not None else json.dumps({"recipes": list(recipes)}),
                           tool_calls=None)


@pytest.fixture
def uploads_env(tmp_path, monkeypatch):
    """Uploads write to a temp dir; the real data/ and .index-user never change."""
    monkeypatch.setattr(config, "UPLOADS_ENABLED", True)
    monkeypatch.setattr(config, "USER_RECIPES_FILE", tmp_path / "user_recipes.json")
    monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "USER_INDEX_DIR", tmp_path / "index-user")
    yield tmp_path
    from chromadb.api.client import SharedSystemClient
    retriever._store.clear()
    SharedSystemClient.clear_system_cache()   # release the temp sqlite file


def _txt(tmp_path, text=SOURCE_TEXT, name="family.txt"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _text_pdf(path, lines):
    """A minimal one-page PDF with a real text layer (no PDF library writes text)."""
    body = "BT /F1 12 Tf 72 720 Td 14 TL " + " ".join(f"({ln}) '" for ln in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(body)} >>\nstream\n{body}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for n, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)
    return path


# --------------------------------------------------------------------------
# File -> text
# --------------------------------------------------------------------------
def test_text_from_docx_txt_and_md(tmp_path):
    import docx
    d = docx.Document()
    d.add_paragraph("Masala Chai")
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "milk", "250 ml"
    d.add_paragraph("Boil everything.")
    d.save(tmp_path / "chai.docx")
    text = uploads.extract_text(tmp_path / "chai.docx")[0][1]
    assert text.index("Masala Chai") < text.index("milk | 250 ml") < text.index("Boil everything.")

    assert "Lemon Drizzle" in uploads.extract_text(_txt(tmp_path))[0][1]
    assert uploads.extract_text(_txt(tmp_path, "# Dal\n", "dal.md"))[0][1] == "# Dal\n"


def test_text_pdf_is_read_and_scanned_pdf_is_rejected(tmp_path):
    pdf = _text_pdf(tmp_path / "book.pdf", ["Tomato Soup", "Ingredients: 6 tomatoes, 1 onion, salt",
                                            "Method: simmer for 20 minutes and blend until smooth."])
    pages = uploads.extract_text(pdf)
    assert pages[0][0] == 1 and "Tomato Soup" in pages[0][1]

    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(612, 792)
    w.write(tmp_path / "scan.pdf")
    with pytest.raises(uploads.UploadError, match="scanned"):
        uploads.extract_text(tmp_path / "scan.pdf")


@pytest.mark.parametrize("name,size,match", [("old.doc", 10, ".docx"), ("x.png", 10, "Unsupported"),
                                             ("a.txt", 0, "empty"), ("a.pdf", 10 ** 9, "MB")])
def test_bad_files_fail_before_any_model_call(name, size, match):
    with pytest.raises(uploads.UploadError, match=match):
        uploads.check_file(name, size)


def test_windows_overlap_and_cover_every_paragraph():
    paras = [f"para {i} " + "x" * 90 for i in range(30)]
    wins = uploads.windows([(1, "\n\n".join(paras[:15])), (2, "\n\n".join(paras[15:]))], size=500, overlap=200)
    assert len(wins) > 1
    joined = "\n\n".join(w["text"] for w in wins)
    assert all(p in joined for p in paras)
    assert all(len(w["text"]) <= 600 for w in wins)
    first, second = wins[0]["text"].split("\n\n"), wins[1]["text"].split("\n\n")
    assert first[-1] in second and second[0] in first   # the edge paragraphs are seen by both windows
    assert wins[-1]["page"] == 2


# --------------------------------------------------------------------------
# Ingest -> corpus, index, safety
# --------------------------------------------------------------------------
def test_upload_becomes_an_undeclared_corpus_recipe(uploads_env, fake_llm):
    fake = fake_llm([reply(LEMON_CAKE)])
    progress = []
    res = uploads.ingest_file(_txt(uploads_env), "family.txt", on_progress=lambda d, t: progress.append((d, t)))

    key = "u_grandma_s_lemon_drizzle_cake@upload"
    assert [r["key"] for r in res["recipes"]] == [key] and progress == [(1, 1)]
    assert "Lemon Drizzle" in fake.requests[0]["messages"][1]["content"]
    r = corpus.get_by_key(key)
    assert r["declared"] is False and r["allergens"] == [] and r["source"]["filename"] == "family.txt"
    assert corpus.card_path(key).exists() and "NOT declared" in corpus.card_path(key).read_text(encoding="utf-8")
    assert (config.UPLOADS_DIR / f"{res['file_id']}.txt").exists()

    # an allergen check can never come back SAFE without a declaration
    assert safety.check_declaration(r, ["DAIRY"])["verdict"] == "UNDECLARED"
    assert safety.check_declaration(r, ["SESAME"])["verdict"] == "UNDECLARED"
    swapped = safety.check_substituted(r, [{"from": "butter", "to": "olive oil"}], ["DAIRY"])
    assert swapped["verdict"] == "UNDECLARED"

    hits = retriever.search("lemon drizzle cake")
    assert hits["results"][0]["recipe"] == key
    excl = retriever.search("lemon drizzle cake", exclude_allergens=["sesame"])
    assert key not in [h["recipe"] for h in excl["results"]] and key in excl["excluded_undeclared"]
    assert key in matching.match(["flour", "eggs"], exclude_allergens=["sesame"])["excluded_undeclared"]


def test_mcp_check_allergens_on_an_upload_says_undeclared(uploads_env, fake_llm):
    from pantry import mcp_server
    fake_llm([reply(LEMON_CAKE)])
    uploads.ingest_file(_txt(uploads_env), "family.txt")
    ctx = SimpleNamespace(request_context=SimpleNamespace(meta={}))
    out = json.loads(mcp_server.check_allergens("u_grandma_s_lemon_drizzle_cake", "upload", ["nuts"], ctx=ctx))
    assert out["verdict"] == "UNDECLARED"


def test_same_file_twice_makes_no_second_model_call(uploads_env, fake_llm):
    fake = fake_llm([reply(LEMON_CAKE)])
    path = _txt(uploads_env)
    first = uploads.ingest_file(path, "family.txt")
    again = uploads.ingest_file(path, "copy.txt")
    assert again["duplicate"] and again["file_id"] == first["file_id"] and len(fake.requests) == 1
    assert len(uploads.list_uploads()) == 1


def test_bad_replies_are_skipped_not_stored(uploads_env, fake_llm, monkeypatch):
    monkeypatch.setitem(config.UPLOAD_LIMITS, "window_chars", 60)
    monkeypatch.setitem(config.UPLOAD_LIMITS, "overlap_chars", 0)
    no_method = dict(LEMON_CAKE, title="Half a recipe", method=[])
    fake_llm([reply(raw="sorry, no JSON here"), reply(no_method, LEMON_CAKE)] + [reply()] * 20)
    res = uploads.ingest_file(_txt(uploads_env, SOURCE_TEXT * 2), "family.txt")
    assert [r["title"] for r in res["recipes"]] == ["Grandma's Lemon Drizzle Cake"]
    assert any("unreadable" in s for s in res["skipped"]) and any("Half a recipe" in s for s in res["skipped"])


def test_no_recipes_found_is_an_error_and_stores_nothing(uploads_env, fake_llm):
    fake_llm([reply()])
    with pytest.raises(uploads.UploadError, match="No complete recipes"):
        uploads.ingest_file(_txt(uploads_env, "Just a story about my grandmother."), "story.txt")
    assert uploads.list_uploads() == []


def test_ids_never_collide_with_the_library_or_each_other(uploads_env, fake_llm):
    fake_llm([reply(dict(LEMON_CAKE, title="Idli")), reply(dict(LEMON_CAKE, title="Idli"))])
    a = uploads.ingest_file(_txt(uploads_env, "one idli", "a.txt"), "a.txt")
    b = uploads.ingest_file(_txt(uploads_env, "two idli", "b.txt"), "b.txt")
    assert a["recipes"][0]["key"] == "u_idli@upload" and b["recipes"][0]["key"] == "u_idli_2@upload"
    assert not corpus.is_upload(corpus.get_by_key("idli@original"))   # the library entry is untouched


def test_delete_removes_recipes_chunks_and_files(uploads_env, fake_llm):
    fake_llm([reply(LEMON_CAKE)])
    res = uploads.ingest_file(_txt(uploads_env), "family.txt")
    key = res["recipes"][0]["key"]
    assert retriever.search("lemon drizzle cake")["results"][0]["recipe"] == key
    out = uploads.delete_upload(res["file_id"])
    assert out["removed"] == [key]
    assert corpus.get_by_key(key) is None and uploads.list_uploads() == []
    assert key not in [h["recipe"] for h in retriever.search("lemon drizzle cake")["results"]]
    assert not corpus.card_path(key).exists()
    with pytest.raises(KeyError):
        uploads.delete_upload(res["file_id"])


def test_uploads_disabled_hides_the_file(uploads_env, fake_llm, monkeypatch):
    fake_llm([reply(LEMON_CAKE)])
    uploads.ingest_file(_txt(uploads_env), "family.txt")
    monkeypatch.setattr(config, "UPLOADS_ENABLED", False)   # PANTRY_USER_RECIPES=0, as evals run
    assert corpus.get_by_key("u_grandma_s_lemon_drizzle_cake@upload") is None
    assert all(not k.startswith("u_") for k in
               (h["recipe"] for h in retriever.search("lemon drizzle cake")["results"]))


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from pantry import api
    return TestClient(api.app)   # no `with`: the lifespan (MCP subprocess) is not needed here


def test_api_upload_streams_progress_then_recipes(uploads_env, fake_llm, client):
    fake_llm([reply(LEMON_CAKE)])
    r = client.post("/api/uploads", files={"file": ("family.txt", SOURCE_TEXT.encode(), "text/plain")})
    events = [json.loads(line) for line in r.text.splitlines()]
    assert r.status_code == 200 and [e["type"] for e in events] == ["progress", "done"]
    assert events[-1]["recipes"][0]["key"] == "u_grandma_s_lemon_drizzle_cake@upload"

    listed = client.get("/api/uploads").json()["files"]
    assert listed[0]["filename"] == "family.txt"
    rec = client.get("/api/recipes/u_grandma_s_lemon_drizzle_cake@upload").json()
    assert rec["source"] == "upload" and rec["declared"] is False and rec["upload"]["filename"] == "family.txt"
    assert client.get("/api/recipes/idli@original").json()["source"] == "library"
    assert client.delete(f"/api/uploads/{listed[0]['file_id']}").status_code == 200
    assert client.delete(f"/api/uploads/{listed[0]['file_id']}").status_code == 404


def test_api_upload_errors(uploads_env, fake_llm, client, monkeypatch):
    r = client.post("/api/uploads", files={"file": ("book.doc", b"x", "application/msword")})
    assert r.status_code == 400 and ".docx" in r.json()["detail"]

    fake_llm([reply()])
    r = client.post("/api/uploads", files={"file": ("story.txt", b"once upon a time", "text/plain")})
    assert json.loads(r.text.splitlines()[-1]) == {
        "type": "error", "message": "No complete recipes (title, ingredients and method) were found in this file."}

    monkeypatch.setattr(config, "UPLOADS_ENABLED", False)
    assert client.post("/api/uploads", files={"file": ("a.txt", b"x", "text/plain")}).status_code == 501
    assert client.get("/api/uploads").status_code == 501
    assert client.get("/api/health").json()["uploads"] is False
