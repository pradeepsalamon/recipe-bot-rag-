const API_URL = 'http://localhost:8000/api'

export async function askQuestion(question) {
  const res = await fetch(`${API_URL}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
  if (!res.ok) {
    throw new Error(`API error ${res.status}`)
  }
  return res.json()
}
