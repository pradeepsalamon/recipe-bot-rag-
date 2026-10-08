"""
Fill the log with a week of traffic so the support drill has a haystack.

Every request here is a REAL call through pipeline.answer(): real retrieval,
real Groq generation, real tokens and cost. The only synthetic part is the
request time. We can't wait a week, so each request gets a `ts` spread over
the previous 7 days (busier at breakfast, lunch and dinner, IST). The true
wall-clock time is kept in `logged_at` and every record says
source="simulated_traffic", so nobody can mistake this for real users.

    python simulate_traffic.py --count 120
"""
import argparse
import random
import time
from datetime import datetime, timedelta, timezone

import pipeline

IST = timezone(timedelta(hours=5, minutes=30))

# What people actually ask a South-Indian recipe bot. Mostly facts and
# how-tos, a fair number of swaps, a handful of diet questions, some junk.
QUESTIONS = {
    "fact": [
        "How much salt is used in the Idli recipe?",
        "What is the ratio of urad dal in the Dosa recipe?",
        "How many cashews are needed for Ven Pongal?",
        "How long should the Idli batter ferment?",
        "How long do I soak the rice for dosa?",
        "How long should Rasam simmer after adding the toor dal?",
        "What is the yield for the Rasam recipe?",
        "How many idlis does the recipe make?",
        "How much water goes into Ven Pongal?",
        "How long do I steam idli?",
        "How much toor dal is in Sambar?",
        "How much tamarind pulp goes in Rasam?",
        "How many vadas does the Medu Vada recipe make?",
        "How many whistles for pongal in the pressure cooker?",
        "How much fenugreek goes into dosa batter?",
        "How much ghee does Ven Pongal use?",
        "What vegetables go in Sambar?",
        "How long should I soak urad dal for Medu Vada?",
    ],
    "how_to": [
        "How do I make crispy Dosa?",
        "Why should Rasam only froth slightly when ready?",
        "How do I get soft idlis?",
        "How do I shape medu vada?",
        "What consistency should dosa batter be?",
        "How do I know the idli batter has fermented enough?",
        "How do I temper the sambar?",
        "Why is my medu vada batter too runny?",
    ],
    "swap": [
        "Can I use oil instead of ghee in Rasam?",
        "Can I use brown rice for dosa?",
        "Can I skip the onion in medu vada?",
        "Can I use lemon instead of tamarind in rasam?",
        "Can I replace idli rice with raw rice?",
        "Can I use moong dal instead of toor dal in sambar?",
        "What can I use instead of curry leaves in pongal?",
        "Can I leave out the fenugreek in idli batter?",
    ],
    "dietary": [
        "Is Idli vegan?",
        "What allergens are in Ven Pongal?",
        "Is Sambar gluten-free?",
        "Is Medu Vada nut-free?",
        "Is Dosa vegan?",
        "Is Rasam dairy-free?",
        "Does Ven Pongal contain nuts?",
        "Which of these recipes are vegan?",
    ],
    "dietary_swap": [
        "I'm vegan, what can I use instead of ghee in Ven Pongal?",
        "What's a dairy-free swap for the fat in Rasam?",
        "My guest has a nut allergy - what can I use instead of cashews in pongal?",
        "Gluten-free substitute for asafoetida in sambar?",
        "I'm lactose intolerant, can I replace the ghee in pongal with oil?",
        "Dairy-free alternative for tempering Ven Pongal?",
        "I'm dairy-free. Is the Rasam recipe safe for me as written?",
    ],
    "scaling": [
        "Double the sambar for 8 people - how much toor dal?",
        "How much rice for pongal for 8 servings?",
        "Halve the idli recipe - how much urad dal?",
    ],
    "out_of_scope": [
        "How do I make chocolate cake?",
        "Tell me a joke about food.",
        "How many calories are in Idli?",
        "Who invented Idli?",
        "How much does it cost to make dosa?",
        "What's the weather like today?",
    ],
}
MIX = {"fact": 34, "how_to": 16, "swap": 14, "dietary": 12,
       "dietary_swap": 8, "scaling": 6, "out_of_scope": 10}

# Hour-of-day weights (IST): breakfast, lunch and dinner peaks.
HOUR_WEIGHTS = [1, 1, 0, 0, 0, 1, 4, 8, 9, 5, 3, 4, 7, 6, 3, 2, 3, 5, 8, 9, 7, 4, 2, 1]


def make_users(rng, n=24):
    # A few heavy users and a long tail, like any real app.
    users = [f"u{rng.randint(1000, 9999)}" for _ in range(n)]
    weights = [max(1, int(30 / (i + 1))) for i in range(n)]
    return users, weights


def make_schedule(rng, count, days=7):
    """Random request times over the last `days` days, in UTC."""
    today = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    times = []
    for _ in range(count):
        day = today - timedelta(days=rng.randint(1, days))
        hour = rng.choices(range(24), weights=HOUR_WEIGHTS)[0]
        t = day + timedelta(hours=hour, minutes=rng.randint(0, 59), seconds=rng.randint(0, 59))
        times.append(t.astimezone(timezone.utc))
    return sorted(times)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=120)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--pause", type=float, default=7.0,
                        help="seconds between calls; keeps us under Groq's 8k tokens/min")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    users, user_weights = make_users(rng)
    kinds, kind_weights = zip(*MIX.items())
    sessions = {}  # user -> (session_id, last ts), new session after 30 min idle

    for i, ts in enumerate(make_schedule(rng, args.count), start=1):
        user = rng.choices(users, weights=user_weights)[0]
        kind = rng.choices(kinds, weights=kind_weights)[0]
        question = rng.choice(QUESTIONS[kind])

        session_id, last = sessions.get(user, (None, None))
        if last is None or ts - last > timedelta(minutes=30):
            session_id = f"s_{rng.getrandbits(32):08x}"
        sessions[user] = (session_id, ts)

        # Pinned to v1: this is "last week", before the dairy fix existed.
        rec = pipeline.answer(question, user_id=user, session_id=session_id,
                              release="v1", ts=ts, source="simulated_traffic")
        print(f"[{i:>3}/{args.count}] {rec['ts']} {user} {rec['input_type']:<13} "
              f"{rec['status']} ${rec['totals']['cost_usd']:.6f}  {question[:60]}", flush=True)
        time.sleep(args.pause)


if __name__ == "__main__":
    main()
