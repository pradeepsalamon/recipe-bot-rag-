import { useState, useRef, useEffect } from 'react'
import { askQuestion } from './api.js'

let nextId = 1

export default function App() {
  const [messages, setMessages] = useState([
    {
      id: 0,
      role: 'assistant',
      text: 'Hi! Ask me anything about the Tamil Nadu recipes — ingredients, method, yields or notes.',
      sources: [],
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  async function handleSend(e) {
    e.preventDefault()
    const question = input.trim()
    if (!question || loading) return

    setInput('')
    setMessages((m) => [...m, { id: nextId++, role: 'user', text: question, sources: [] }])
    setLoading(true)

    try {
      const data = await askQuestion(question)
      setMessages((m) => [
        ...m,
        { id: nextId++, role: 'assistant', text: data.answer, sources: data.sources },
      ])
    } catch (err) {
      setMessages((m) => [
        ...m,
        {
          id: nextId++,
          role: 'assistant',
          text: 'Sorry, I could not reach the recipe service. Is the backend running on port 8000?',
          sources: [],
          error: true,
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app">
      <header className="header">
        <h1>🍲 Ask My Recipes</h1>
        <p>RAG-powered assistant for Tamil Nadu recipe cards</p>
      </header>

      <main className="chat">
        {messages.map((msg) => (
          <div key={msg.id} className={`message ${msg.role}${msg.error ? ' error' : ''}`}>
            <div className="bubble">
              <p className="text">{msg.text}</p>
              {msg.sources?.length > 0 && (
                <div className="sources">
                  <span className="sources-label">Sources:</span>
                  {msg.sources.map((s) => (
                    <span key={s.chunk_id} className="chip" title={s.chunk_id}>
                      {s.recipe_id}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div className="message assistant">
            <div className="bubble typing">
              <span></span>
              <span></span>
              <span></span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </main>

      <form className="input-bar" onSubmit={handleSend}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="e.g. How much salt is used in Idli?"
          autoFocus
        />
        <button type="submit" disabled={!input.trim() || loading}>
          Send
        </button>
      </form>
    </div>
  )
}
