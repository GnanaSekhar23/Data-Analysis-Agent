import { useState, useEffect, useRef } from "react"
import ReactMarkdown from "react-markdown"

function QuestionPill({ question, onClick }) {
  return (
    <button
      onClick={() => onClick(question)}
      className="text-left px-3 py-2 rounded-lg bg-gray-100 hover:bg-blue-50 hover:text-blue-700 text-sm text-gray-600 transition-colors border border-gray-200 hover:border-blue-300"
    >
      {question}
    </button>
  )
}

function DataTable({ rows, columns, totalRows }) {
  if (!rows || rows.length === 0) return null
  return (
    <div className="mt-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-gray-600">Raw Data</h3>
        <span className="text-xs text-gray-400">Showing {rows.length} of {totalRows} rows</span>
      </div>
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              {columns.map(col => (
                <th key={col} className="px-4 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider border-b">{col}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.map((row, i) => (
              <tr key={i} className="hover:bg-gray-50">
                {columns.map(col => (
                  <td key={col} className="px-4 py-2 text-gray-700 whitespace-nowrap">
                    {row[col] !== null && row[col] !== undefined ? String(row[col]) : "—"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function StatusBadge({ node, message }) {
  const icons = { starting: "⚡", inspect_schema: "🔍", generate_sql: "✍️", run_query: "⚙️", analyze: "🧠", visualize: "📊" }
  return (
    <div className="flex items-center gap-2 text-sm text-blue-600 bg-blue-50 px-3 py-2 rounded-lg">
      <span className="animate-pulse">●</span>
      <span>{icons[node] || "⚡"} {message}</span>
    </div>
  )
}

export default function App() {
  const [question, setQuestion]       = useState("")
  const [loading, setLoading]         = useState(false)
  const [status, setStatus]           = useState(null)
  const [sql, setSql]                 = useState("")
  const [analysis, setAnalysis]       = useState("")
  const [chart, setChart]             = useState(null)
  const [chartType, setChartType]     = useState("")
  const [tableData, setTableData]     = useState(null)
  const [error, setError]             = useState("")
  const [sampleQuestions, setSample]  = useState([])
  const [datasetInfo, setDatasetInfo] = useState(null)
  const [showSql, setShowSql]         = useState(false)
  const textareaRef                   = useRef(null)

  useEffect(() => {
    fetch("/sample-questions").then(r => r.json()).then(d => setSample(d.questions)).catch(() => {})
    fetch("/dataset-info").then(r => r.json()).then(d => setDatasetInfo(d)).catch(() => {})
  }, [])

  const handleEvent = (event, payload) => {
    console.log("SSE:", event, event === "chart" ? `image_length=${payload.image?.length}` : payload)
    switch (event) {
      case "status":   setStatus(payload); break
      case "sql":      setSql(payload.sql || ""); break
      case "analysis": setAnalysis(payload.text || ""); break
      case "chart":
        if (payload.image) {
          setChart(payload.image)
          setChartType(payload.chart_type || "chart")
        }
        break
      case "data":     setTableData(payload); break
      case "error":    setError(payload.message || "Unknown error"); break
      case "done":     setStatus(null); break
    }
  }

  const handleSubmit = async (q) => {
    const questionText = q || question
    if (!questionText.trim()) return

    setLoading(true)
    setStatus(null)
    setSql("")
    setAnalysis("")
    setChart(null)
    setChartType("")
    setTableData(null)
    setError("")
    setShowSql(false)
    if (q) setQuestion(q)

    try {
      const response = await fetch("/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: questionText }),
      })

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // Split on double newline — each SSE message ends with \n\n
        const messages = buffer.split("\n\n")
        // Keep the last incomplete message in buffer
        buffer = messages.pop() || ""

        for (const message of messages) {
          if (!message.trim()) continue
          let eventName = ""
          let dataStr = ""

          for (const line of message.split("\n")) {
            if (line.startsWith("event: ")) {
              eventName = line.slice(7).trim()
            } else if (line.startsWith("data: ")) {
              dataStr = line.slice(6).trim()
            }
          }

          if (eventName && dataStr) {
            try {
              const payload = JSON.parse(dataStr)
              handleEvent(eventName, payload)
            } catch (e) {
              console.error("JSON parse error for event:", eventName, e)
            }
          }
        }
      }
    } catch (e) {
      console.error("fetch error:", e)
      setError("Connection error: " + e.message)
    } finally {
      setLoading(false)
      setStatus(null)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">Data Analysis Agent</h1>
            {datasetInfo && (
              <p className="text-sm text-gray-500 mt-0.5">{datasetInfo.name} · {datasetInfo.tables?.length} tables</p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 bg-green-500 rounded-full"></span>
            <span className="text-sm text-gray-500">Connected</span>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8">
        <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-4 mb-6">
          <textarea
            ref={textareaRef}
            value={question}
            onChange={e => setQuestion(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask anything about your data... e.g. What are the top 5 product categories by revenue?"
            className="w-full resize-none text-gray-800 placeholder-gray-400 text-base outline-none min-h-[60px] max-h-[200px]"
            rows={2}
          />
          <div className="flex items-center justify-between mt-3 pt-3 border-t border-gray-100">
            <span className="text-xs text-gray-400">Press Enter to analyze · Shift+Enter for new line</span>
            <button
              onClick={() => handleSubmit()}
              disabled={loading || !question.trim()}
              className="px-5 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? "Analyzing..." : "Analyze"}
            </button>
          </div>
        </div>

        {!analysis && !loading && sampleQuestions.length > 0 && (
          <div className="mb-6">
            <p className="text-sm text-gray-500 mb-3">Try these questions:</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {sampleQuestions.slice(0, 6).map((q, i) => (
                <QuestionPill key={i} question={q} onClick={handleSubmit} />
              ))}
            </div>
          </div>
        )}

        {status && <div className="mb-4"><StatusBadge node={status.node} message={status.message} /></div>}

        {error && (
          <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">⚠️ {error}</div>
        )}

        {(analysis || chart || sql) && (
          <div className="space-y-4">

            {chart && (
              <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6">
                <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">
                  📊 {chartType} chart
                </h2>
                <img
                  src={`data:image/png;base64,${chart}`}
                  alt="Analysis chart"
                  className="w-full rounded-lg"
                />
              </div>
            )}

            {analysis && (
              <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6">
                <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">🧠 Analysis</h2>
                <div className="prose prose-sm max-w-none text-gray-700">
                  <ReactMarkdown>{analysis}</ReactMarkdown>
                </div>
              </div>
            )}

            {sql && (
              <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6">
                <button onClick={() => setShowSql(!showSql)} className="flex items-center justify-between w-full text-left">
                  <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">🔍 Generated SQL</h2>
                  <span className="text-xs text-blue-500">{showSql ? "Hide" : "Show"}</span>
                </button>
                {showSql && (
                  <pre className="mt-4 p-4 bg-gray-50 rounded-lg text-sm text-gray-800 overflow-x-auto whitespace-pre-wrap border border-gray-100">{sql}</pre>
                )}
              </div>
            )}

            {tableData && tableData.rows && tableData.rows.length > 0 && (
              <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6">
                <DataTable rows={tableData.rows} columns={tableData.columns} totalRows={tableData.total_rows} />
              </div>
            )}

          </div>
        )}
      </main>
    </div>
  )
}
