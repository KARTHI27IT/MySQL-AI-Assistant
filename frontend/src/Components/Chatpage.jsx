import { useState, useRef, useEffect, useCallback } from "react";
import axios from "axios";

// ── Constants ────────────────────────────────────────────────
const API_BASE = "http://localhost:8000";

const MSG = {
  USER:      "user",
  ASSISTANT: "assistant",
  SYSTEM:    "system",
  ERROR:     "error",
  LOADING:   "loading",
};

// ── Tiny helpers ─────────────────────────────────────────────
const cls = (...args) => args.filter(Boolean).join(" ");

// ── Loading Dots ─────────────────────────────────────────────
function LoadingDots() {
  return (
    <span className="inline-flex items-center gap-1">
      {[0, 150, 300].map((d, i) => (
        <span
          key={i}
          className="w-2 h-2 rounded-full bg-blue-400 animate-bounce"
          style={{ animationDelay: `${d}ms` }}
        />
      ))}
    </span>
  );
}

// ── Validation Badge ──────────────────────────────────────────
function ValidationBadge({ validation }) {
  if (!validation || validation.valid === null) return null;
  const { valid, reason, original_sql, corrected_sql, used_correction } = validation;
  return (
    <div className={cls(
      "mt-3 rounded-lg border px-3 py-2 text-xs",
      valid
        ? "bg-emerald-50 border-emerald-200 text-emerald-800"
        : used_correction
        ? "bg-amber-50 border-amber-200 text-amber-800"
        : "bg-red-50 border-red-200 text-red-800"
    )}>
      <div className="flex items-center gap-1.5 font-semibold mb-1">
        {valid ? "✅ SQL Validated" : used_correction ? "⚠️ Auto-corrected" : "❌ Validation Failed"}
      </div>
      <p className="opacity-80">{reason}</p>
      {used_correction && corrected_sql && (
        <p className="mt-1 opacity-70 italic">Corrected query used instead of original.</p>
      )}
    </div>
  );
}

// ── SQL Code Block ────────────────────────────────────────────
function SQLBlock({ sql, label = "Generated SQL" }) {
  const [copied, setCopied] = useState(false);
  if (!sql) return null;
  const copy = async () => {
    try { await navigator.clipboard.writeText(sql); setCopied(true); setTimeout(() => setCopied(false), 2000); }
    catch {}
  };
  return (
    <div className="relative group mt-3 mb-1">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-semibold uppercase tracking-wide text-gray-400">{label}</span>
        <button
          onClick={copy}
          className="text-xs px-2 py-0.5 rounded bg-gray-700 text-gray-200 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-gray-600"
        >
          {copied ? "✓ Copied" : "Copy"}
        </button>
      </div>
      <pre className="bg-gray-950 text-emerald-400 text-xs font-mono rounded-lg p-3 overflow-x-auto border border-gray-800 leading-relaxed">
        {sql}
      </pre>
    </div>
  );
}

// ── Results Table ─────────────────────────────────────────────
function ResultTable({ columns, rows, rowCount, tableName, compact = false }) {
  const [page, setPage] = useState(0);
  const PER_PAGE = compact ? 10 : 20;
  const totalPages = Math.ceil((rows?.length || 0) / PER_PAGE);
  const visibleRows = rows?.slice(page * PER_PAGE, page * PER_PAGE + PER_PAGE) || [];

  if (!rows || rows.length === 0) {
    return (
      <div className="mt-3 py-6 text-center text-gray-400 text-sm border border-gray-200 rounded-lg bg-gray-50">
        No results found
      </div>
    );
  }

  return (
    <div className="mt-3">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs text-gray-400 font-medium uppercase tracking-wide">
          {tableName ? `📋 ${tableName}` : "Results"} · {rowCount} row{rowCount !== 1 ? "s" : ""}
        </span>
        {totalPages > 1 && (
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <button disabled={page === 0} onClick={() => setPage(p => p - 1)}
              className="px-2 py-0.5 rounded border border-gray-200 hover:bg-gray-100 disabled:opacity-40">‹</button>
            <span>{page + 1}/{totalPages}</span>
            <button disabled={page >= totalPages - 1} onClick={() => setPage(p => p + 1)}
              className="px-2 py-0.5 rounded border border-gray-200 hover:bg-gray-100 disabled:opacity-40">›</button>
          </div>
        )}
      </div>
      <div className="overflow-x-auto rounded-lg border border-gray-200 shadow-sm">
        <table className="min-w-full divide-y divide-gray-100 bg-white text-sm">
          <thead className="bg-gray-50">
            <tr>
              {columns.map((col, i) => (
                <th key={i} className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {visibleRows.map((row, ri) => (
              <tr key={ri} className="hover:bg-blue-50 transition-colors">
                {row.map((cell, ci) => (
                  <td key={ci} className="px-3 py-2 text-gray-700 whitespace-nowrap max-w-[240px] truncate">
                    {cell === null || cell === undefined
                      ? <span className="text-gray-300 italic text-xs">NULL</span>
                      : String(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Rollback Timer ────────────────────────────────────────────
function RollbackTimer({ expiresIn }) {
  return <span className="text-xs text-amber-600">{expiresIn} remaining</span>;
}

// ── Write Confirm Modal ───────────────────────────────────────
function ConfirmModal({ pending, onConfirm, onCancel }) {
  const [checked, setChecked] = useState(false);
  if (!pending) return null;

  const { sql, preview, validation } = pending;
  const action = preview?.action || "WRITE";
  const count  = preview?.affected_count ?? 0;
  const sample = preview?.sample || [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-2xl w-full max-h-[90vh] flex flex-col overflow-hidden">
        <div className="bg-amber-50 border-b border-amber-200 px-5 py-4 flex items-start gap-3 shrink-0">
          <span className="text-2xl mt-0.5">⚠️</span>
          <div>
            <h3 className="font-bold text-gray-800 text-lg">Confirm {action} Operation</h3>
            <p className="text-sm text-amber-700 mt-0.5">
              {preview?.warning || `This will ${action.toLowerCase()} ${count} row(s) in your database.`}
            </p>
          </div>
        </div>
        <div className="overflow-y-auto flex-1 px-5 py-4 space-y-4">
          <SQLBlock sql={sql} label="SQL to Execute" />
          {validation && <ValidationBadge validation={validation} />}
          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
              Impact Preview — {count} row{count !== 1 ? "s" : ""} affected
            </p>
            {sample.length > 0 ? (
              <ResultTable
                columns={Object.keys(sample[0])}
                rows={sample.map(r => Object.values(r))}
                rowCount={sample.length}
                compact
              />
            ) : action === "INSERT" ? (
              <div className="text-sm text-gray-500 italic bg-gray-50 rounded-lg p-3 border border-gray-200">
                New row will be inserted.
                {preview?.columns && (
                  <div className="mt-2 text-xs"><strong>Columns:</strong> {preview.columns.join(", ")}</div>
                )}
              </div>
            ) : (
              <p className="text-sm text-gray-400 italic bg-gray-50 rounded-lg p-3 border border-gray-200">
                Could not preview affected rows.
              </p>
            )}
          </div>
          <div className="bg-blue-50 border border-blue-200 rounded-lg px-3 py-2 text-xs text-blue-700">
            ℹ️ After execution, a <strong>Rollback</strong> button will appear for 5 minutes to undo this operation.
          </div>
          <label className="flex items-start gap-3 p-3 bg-red-50 border border-red-200 rounded-lg cursor-pointer hover:bg-red-100 transition-colors">
            <input
              type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)}
              className="mt-0.5 w-4 h-4 text-red-600 rounded border-gray-300 focus:ring-red-500 shrink-0"
            />
            <span className="text-sm text-red-800">
              I understand this will <strong>modify the database</strong>. Changes can be undone via Rollback within 5 minutes.
            </span>
          </label>
        </div>
        <div className="px-5 py-4 border-t border-gray-200 flex justify-end gap-3 bg-gray-50 shrink-0">
          <button onClick={onCancel}
            className="px-4 py-2 text-gray-700 hover:bg-gray-200 rounded-lg font-medium transition-colors">
            Cancel
          </button>
          <button
            onClick={() => { if (checked) onConfirm(); }}
            disabled={!checked}
            className={cls(
              "px-4 py-2 rounded-lg font-medium text-white transition-all shadow-sm",
              checked ? "bg-red-600 hover:bg-red-700 cursor-pointer" : "bg-gray-300 cursor-not-allowed"
            )}
          >
            ✅ Execute {action}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Insert Row Modal ──────────────────────────────────────────
function InsertModal({ open, selectedDB, onClose, onSuccess, addMsg }) {
  const [step, setStep]           = useState("select-table"); // "select-table" | "fill-form"
  const [tables, setTables]       = useState([]);
  const [tablesLoading, setTablesLoading] = useState(false);
  const [selectedTable, setSelectedTable] = useState("");
  const [columns, setColumns]     = useState([]);
  const [colsLoading, setColsLoading] = useState(false);
  const [formData, setFormData]   = useState({});
  const [formErrors, setFormErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");

  // Reset when opened
  useEffect(() => {
    if (open) {
      setStep("select-table");
      setSelectedTable("");
      setColumns([]);
      setFormData({});
      setFormErrors({});
      setSubmitError("");
      loadTables();
    }
  }, [open]);

  const loadTables = async () => {
    setTablesLoading(true);
    try {
      const r = await axios.get(`${API_BASE}/insert/tables/${selectedDB}`, { timeout: 8000 });
      setTables(r.data.tables || []);
    } catch (e) {
      setTables([]);
    } finally {
      setTablesLoading(false);
    }
  };

  const loadColumns = async (table) => {
    setColsLoading(true);
    try {
      const r = await axios.get(`${API_BASE}/insert/schema/${selectedDB}/${table}`, { timeout: 8000 });
      const cols = r.data.columns || [];
      setColumns(cols);
      // Initialize form data: skip auto_increment PKs
      const init = {};
      cols.forEach(col => {
        if (!col.auto_increment) {
          init[col.name] = col.default_value !== null && col.default_value !== undefined
            ? String(col.default_value)
            : "";
        }
      });
      setFormData(init);
      setFormErrors({});
      setStep("fill-form");
    } catch (e) {
      setSubmitError("Failed to load table columns.");
    } finally {
      setColsLoading(false);
    }
  };

  const handleTableSelect = (table) => {
    setSelectedTable(table);
    loadColumns(table);
  };

  // Determine HTML input type from MySQL data type
  const getInputType = (col) => {
    const t = col.data_type?.toLowerCase() || "";
    if (["int","bigint","smallint","tinyint","mediumint","year"].includes(t)) return "number";
    if (["float","double","decimal","numeric","real"].includes(t)) return "number";
    if (t === "date") return "date";
    if (["datetime","timestamp"].includes(t)) return "datetime-local";
    if (t === "time") return "time";
    if (["tinyint"].includes(t) && col.display_type?.includes("(1)")) return "checkbox";
    return "text";
  };

  const getInputAttrs = (col) => {
    const t = col.data_type?.toLowerCase() || "";
    const attrs = {};
    if (["float","double","decimal","numeric","real"].includes(t)) {
      attrs.step = "any";
    }
    if (col.char_max_length) {
      attrs.maxLength = col.char_max_length;
    }
    return attrs;
  };

  const validate = () => {
    const errs = {};
    columns.forEach(col => {
      if (col.auto_increment) return;
      const val = formData[col.name];
      if (!col.nullable && !col.has_default && (val === "" || val === undefined || val === null)) {
        errs[col.name] = "This field is required";
      }
    });
    setFormErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleSubmit = async () => {
    if (!validate()) return;
    setSubmitting(true);
    setSubmitError("");

    // Build payload: exclude empty optional fields (send null for nullable)
    const payload = {};
    columns.forEach(col => {
      if (col.auto_increment) return;
      const val = formData[col.name];
      if (val === "" || val === undefined) {
        payload[col.name] = null;
      } else {
        payload[col.name] = val;
      }
    });

    try {
      const r = await axios.post(`${API_BASE}/insert`, {
        database: selectedDB,
        table: selectedTable,
        data: payload,
      }, { timeout: 20000 });

      if (r.data.success) {
        onSuccess(r.data, selectedTable);
        onClose();
      } else {
        setSubmitError(r.data.error || "Insert failed");
      }
    } catch (e) {
      setSubmitError(e.response?.data?.error || e.message || "Insert request failed");
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[92vh] flex flex-col overflow-hidden">

        {/* Header */}
        <div className="bg-gradient-to-r from-emerald-600 to-teal-600 px-5 py-4 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            <span className="text-white text-xl">➕</span>
            <div>
              <h3 className="text-white font-bold text-base">Insert New Row</h3>
              <p className="text-emerald-100 text-xs mt-0.5">
                {step === "select-table" ? `Database: ${selectedDB}` : `Table: ${selectedTable}`}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-white/70 hover:text-white text-xl font-light transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Step indicator */}
        <div className="flex items-center gap-0 px-5 py-2.5 bg-gray-50 border-b border-gray-200 shrink-0">
          <div className={cls(
            "flex items-center gap-1.5 text-xs font-medium px-2 py-1 rounded",
            step === "select-table" ? "text-emerald-700 bg-emerald-50" : "text-gray-400"
          )}>
            <span className={cls(
              "w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold",
              step === "select-table" ? "bg-emerald-600 text-white" : "bg-gray-200 text-gray-500"
            )}>1</span>
            Select Table
          </div>
          <div className="flex-1 h-px bg-gray-200 mx-2" />
          <div className={cls(
            "flex items-center gap-1.5 text-xs font-medium px-2 py-1 rounded",
            step === "fill-form" ? "text-emerald-700 bg-emerald-50" : "text-gray-400"
          )}>
            <span className={cls(
              "w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold",
              step === "fill-form" ? "bg-emerald-600 text-white" : "bg-gray-200 text-gray-500"
            )}>2</span>
            Fill Fields
          </div>
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1 p-5">

          {/* ── Step 1: Table selector ── */}
          {step === "select-table" && (
            <div>
              {tablesLoading ? (
                <div className="flex items-center justify-center py-12 gap-2 text-gray-400">
                  <span className="w-5 h-5 border-2 border-gray-300 border-t-emerald-500 rounded-full animate-spin" />
                  <span className="text-sm">Loading tables…</span>
                </div>
              ) : tables.length === 0 ? (
                <div className="text-center py-8 text-gray-400 text-sm">No tables found in <strong>{selectedDB}</strong></div>
              ) : (
                <div className="space-y-2">
                  <p className="text-xs text-gray-500 mb-3 font-medium uppercase tracking-wide">
                    {tables.length} table{tables.length !== 1 ? "s" : ""} — click one to continue
                  </p>
                  {tables.map(table => (
                    <button
                      key={table.name}
                      onClick={() => handleTableSelect(table.name)}
                      disabled={colsLoading}
                      className="w-full flex items-center justify-between px-4 py-3 rounded-xl border border-gray-200 bg-white hover:border-emerald-400 hover:bg-emerald-50 text-left transition-all group disabled:opacity-50"
                    >
                      <div className="flex items-center gap-3">
                        <span className="text-lg">📋</span>
                        <div>
                          <p className="text-sm font-medium text-gray-800">{table.name}</p>
                          {table.row_count !== undefined && (
                            <p className="text-xs text-gray-400">{table.row_count.toLocaleString()} rows · {table.column_count} columns</p>
                          )}
                        </div>
                      </div>
                      <span className="text-gray-300 group-hover:text-emerald-500 transition-colors text-lg">→</span>
                    </button>
                  ))}
                </div>
              )}
              {colsLoading && (
                <div className="flex items-center justify-center py-4 gap-2 text-gray-400 mt-2">
                  <span className="w-4 h-4 border-2 border-gray-300 border-t-emerald-500 rounded-full animate-spin" />
                  <span className="text-xs">Loading schema…</span>
                </div>
              )}
            </div>
          )}

          {/* ── Step 2: Dynamic form ── */}
          {step === "fill-form" && (
            <div className="space-y-4">
              {/* Back link */}
              <button
                onClick={() => setStep("select-table")}
                className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 transition-colors mb-1"
              >
                ← Back to table list
              </button>

              {columns.map(col => {
                if (col.auto_increment) {
                  return (
                    <div key={col.name} className="opacity-50">
                      <label className="block text-xs font-medium text-gray-500 mb-1">
                        {col.name}
                        <span className="ml-1.5 text-[10px] bg-gray-100 text-gray-400 px-1.5 py-0.5 rounded font-normal uppercase tracking-wide">
                          auto
                        </span>
                      </label>
                      <input
                        type="text"
                        disabled
                        placeholder="Auto-generated"
                        className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg bg-gray-50 text-gray-400 cursor-not-allowed"
                      />
                    </div>
                  );
                }

                const inputType = getInputType(col);
                const extraAttrs = getInputAttrs(col);
                const isRequired = !col.nullable && !col.has_default;
                const hasError = !!formErrors[col.name];

                return (
                  <div key={col.name}>
                    <label className="block text-xs font-medium text-gray-700 mb-1">
                      {col.name}
                      {isRequired && <span className="text-red-500 ml-0.5">*</span>}
                      <span className="ml-1.5 text-[10px] bg-blue-50 text-blue-500 px-1.5 py-0.5 rounded font-normal">
                        {col.display_type || col.data_type}
                      </span>
                      {col.nullable && (
                        <span className="ml-1 text-[10px] text-gray-400 font-normal">nullable</span>
                      )}
                      {col.has_default && col.default_value !== null && (
                        <span className="ml-1 text-[10px] text-gray-400 font-normal">
                          default: {String(col.default_value)}
                        </span>
                      )}
                    </label>

                    {/* ENUM → select */}
                    {col.data_type === "enum" && col.enum_values?.length > 0 ? (
                      <select
                        value={formData[col.name] ?? ""}
                        onChange={e => setFormData(prev => ({ ...prev, [col.name]: e.target.value }))}
                        className={cls(
                          "w-full px-3 py-2 text-sm border rounded-lg bg-white focus:ring-2 focus:ring-emerald-400 focus:border-emerald-400 outline-none transition-shadow",
                          hasError ? "border-red-400 bg-red-50" : "border-gray-300"
                        )}
                      >
                        {(col.nullable || col.has_default) && <option value="">— select or leave empty —</option>}
                        {col.enum_values.map(v => (
                          <option key={v} value={v}>{v}</option>
                        ))}
                      </select>

                    /* TEXT/LONGTEXT → textarea */
                    ) : (col.data_type === "text" || col.data_type === "longtext" || col.data_type === "mediumtext") ? (
                      <textarea
                        value={formData[col.name] ?? ""}
                        onChange={e => setFormData(prev => ({ ...prev, [col.name]: e.target.value }))}
                        placeholder={col.nullable ? "NULL (leave empty)" : `Enter ${col.name}…`}
                        rows={3}
                        className={cls(
                          "w-full px-3 py-2 text-sm border rounded-lg bg-white focus:ring-2 focus:ring-emerald-400 focus:border-emerald-400 outline-none resize-y transition-shadow",
                          hasError ? "border-red-400 bg-red-50" : "border-gray-300"
                        )}
                      />

                    /* BOOLEAN tinyint(1) → checkbox */
                    ) : (col.data_type === "tinyint" && col.display_type?.includes("(1)")) ? (
                      <div className="flex items-center gap-2 mt-1">
                        <input
                          type="checkbox"
                          checked={formData[col.name] === "1" || formData[col.name] === true}
                          onChange={e => setFormData(prev => ({ ...prev, [col.name]: e.target.checked ? "1" : "0" }))}
                          className="w-4 h-4 rounded text-emerald-600 border-gray-300 focus:ring-emerald-400"
                        />
                        <span className="text-sm text-gray-600">
                          {formData[col.name] === "1" || formData[col.name] === true ? "True (1)" : "False (0)"}
                        </span>
                      </div>

                    /* Default: text/number/date input */
                    ) : (
                      <input
                        type={inputType}
                        value={formData[col.name] ?? ""}
                        onChange={e => setFormData(prev => ({ ...prev, [col.name]: e.target.value }))}
                        placeholder={col.nullable ? "NULL (leave empty)" : `Enter ${col.name}…`}
                        {...extraAttrs}
                        className={cls(
                          "w-full px-3 py-2 text-sm border rounded-lg bg-white focus:ring-2 focus:ring-emerald-400 focus:border-emerald-400 outline-none transition-shadow",
                          hasError ? "border-red-400 bg-red-50" : "border-gray-300"
                        )}
                      />
                    )}

                    {hasError && (
                      <p className="mt-1 text-xs text-red-500">⚠ {formErrors[col.name]}</p>
                    )}
                    {col.comment && (
                      <p className="mt-0.5 text-xs text-gray-400 italic">💡 {col.comment}</p>
                    )}
                  </div>
                );
              })}

              {submitError && (
                <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                  <span className="font-semibold">⚠️ Error: </span>{submitError}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        {step === "fill-form" && (
          <div className="px-5 py-4 border-t border-gray-200 flex justify-end gap-3 bg-gray-50 shrink-0">
            <button
              onClick={onClose}
              className="px-4 py-2 text-gray-700 hover:bg-gray-200 rounded-lg font-medium transition-colors text-sm"
            >
              Cancel
            </button>
            <button
              onClick={handleSubmit}
              disabled={submitting}
              className={cls(
                "px-5 py-2 rounded-lg font-medium text-white text-sm transition-all shadow-sm flex items-center gap-2",
                submitting ? "bg-gray-300 cursor-not-allowed" : "bg-gradient-to-r from-emerald-600 to-teal-600 hover:brightness-110"
              )}
            >
              {submitting
                ? <><span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Inserting…</>
                : <>➕ Insert Row</>}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Chat Bubble ───────────────────────────────────────────────
function ChatBubble({ msg, onRollback }) {
  const isUser   = msg.type === MSG.USER;
  const isSystem = msg.type === MSG.SYSTEM;
  const isError  = msg.type === MSG.ERROR;
  const isLoad   = msg.type === MSG.LOADING;

  if (isLoad) {
    return (
      <div className="flex justify-start mb-4">
        <div className="bg-white border border-gray-200 rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-7 h-7 rounded-full bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center text-sm">🤖</div>
            <span className="text-xs text-gray-400">SQL Assistant</span>
          </div>
          <LoadingDots />
        </div>
      </div>
    );
  }

  if (isSystem) {
    return (
      <div className="flex justify-center mb-3">
        <span className="text-xs bg-gray-100 text-gray-500 rounded-full px-3 py-1">{msg.content}</span>
      </div>
    );
  }

  return (
    <div className={cls("flex mb-4", isUser ? "justify-end" : "justify-start")}>
      <div className={cls(
        "max-w-[85%] rounded-2xl px-4 py-3 shadow-md",
        isUser  ? "bg-gradient-to-br from-blue-600 to-blue-700 text-white rounded-br-sm"
        : isError ? "bg-red-50 border border-red-200 text-gray-800 rounded-bl-sm"
        : "bg-white border border-gray-200 text-gray-800 rounded-bl-sm"
      )}>
        <div className="flex items-center gap-2 mb-2">
          <div className={cls(
            "w-7 h-7 rounded-full flex items-center justify-center text-sm font-bold text-white shadow",
            isUser ? "bg-blue-800" : "bg-gradient-to-br from-emerald-500 to-teal-600"
          )}>
            {isUser ? "👤" : "🤖"}
          </div>
          <span className={cls("text-xs font-medium", isUser ? "text-blue-100" : "text-gray-400")}>
            {isUser ? "You" : "SQL Assistant"}
          </span>
        </div>

        <div className="text-sm leading-relaxed">
          {msg.content && <p className="whitespace-pre-wrap">{msg.content}</p>}
          {msg.sql && <SQLBlock sql={msg.sql} />}
          {msg.validation && <ValidationBadge validation={msg.validation} />}

          {msg.columns && msg.result && (
            <ResultTable
              columns={msg.columns}
              rows={msg.result}
              rowCount={msg.row_count || msg.result.length}
            />
          )}

          {msg.query_type === "WRITE" && msg.success && (
            <div className="mt-2 space-y-2">
              <div className="p-2.5 bg-emerald-50 border border-emerald-200 rounded-lg text-xs">
                <p className="font-semibold text-emerald-700">✅ {msg.operation_verb || "Operation"} successful</p>
                {msg.rows_affected !== undefined && (
                  <p className="text-emerald-600 mt-0.5">Rows affected: <strong>{msg.rows_affected}</strong></p>
                )}
                {msg.last_insert_id && (
                  <p className="text-emerald-600">New row ID: <strong>{msg.last_insert_id}</strong></p>
                )}
              </div>
              {msg.table_data && !msg.table_data.error && msg.table_data.columns && (
                <ResultTable
                  columns={msg.table_data.columns}
                  rows={msg.table_data.rows}
                  rowCount={msg.table_data.row_count}
                  tableName={msg.table_data.table}
                  compact
                />
              )}
              {msg.rollback_available && msg.operation_id && (
                <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-xs font-semibold text-amber-800">↩️ Rollback Available</p>
                      {msg.rollback_expires_in && <RollbackTimer expiresIn={msg.rollback_expires_in} />}
                    </div>
                    <button
                      onClick={() => {
                        if (window.confirm(`Undo this INSERT on \`${msg.table_name}\`?\n\nThis cannot be undone again.`)) {
                          onRollback(msg.operation_id);
                        }
                      }}
                      className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white text-xs rounded-lg font-medium shadow-sm transition-colors"
                    >
                      ↩️ Rollback
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {isError && msg.error && (
            <div className="mt-2 p-2.5 bg-red-50 border border-red-200 rounded-lg text-xs">
              <p className="font-semibold text-red-700">⚠️ Error</p>
              <p className="text-red-600 mt-0.5">{msg.error}</p>
              {msg.suggestion && <p className="text-red-400 mt-1 italic">💡 {msg.suggestion}</p>}
            </div>
          )}
        </div>

        <div className={cls(
          "text-xs mt-2.5 pt-2 border-t flex justify-between",
          isUser ? "border-blue-500/30 text-blue-200/60" : "border-gray-100 text-gray-300"
        )}>
          <span>{new Date(msg.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
          {msg.row_count !== undefined && <span>{msg.row_count} rows</span>}
        </div>
      </div>
    </div>
  );
}

// ── Main App ──────────────────────────────────────────────────
export default function App() {
  const [databases,    setDatabases]    = useState([]);
  const [selectedDB,   setSelectedDB]   = useState("");
  const [prompt,       setPrompt]       = useState("");
  const [messages,     setMessages]     = useState([{
    id: 1, type: MSG.SYSTEM,
    content: "👋 Welcome! Load databases, select one, then ask about your data.",
    timestamp: new Date(),
  }]);
  const [loading,      setLoading]      = useState(false);
  const [dbLoading,    setDbLoading]    = useState(false);
  const [pendingWrite, setPendingWrite] = useState(null);
  const [useSchema,    setUseSchema]    = useState(true);
  const [backendOk,    setBackendOk]    = useState(null);
  const [insertOpen,   setInsertOpen]   = useState(false);

  const bottomRef   = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 120) + "px";
    }
  }, [prompt]);

  const checkHealth = useCallback(async () => {
    try {
      const r = await axios.get(`${API_BASE}/health`, { timeout: 3000 });
      setBackendOk(r.data.status === "healthy");
    } catch {
      setBackendOk(false);
    }
  }, []);

  useEffect(() => {
    checkHealth();
    const t = setInterval(checkHealth, 30000);
    return () => clearInterval(t);
  }, [checkHealth]);

  const addMsg = (type, content, extras = {}) => {
    setMessages(prev => [...prev, {
      id: Date.now() + Math.random(),
      type, content, timestamp: new Date(), ...extras
    }]);
  };

  const removeLoadingMsg = id =>
    setMessages(prev => prev.filter(m => m.id !== id));

  const loadDatabases = async () => {
    setDbLoading(true);
    try {
      const r = await axios.get(`${API_BASE}/databases`, { timeout: 6000 });
      setDatabases(r.data.databases || []);
      addMsg(MSG.SYSTEM, `✅ Found ${r.data.databases?.length || 0} database(s) — select one to start`);
    } catch (e) {
      addMsg(MSG.ERROR, "Failed to load databases", {
        error: e.message, suggestion: `Ensure backend is running at ${API_BASE}`
      });
    } finally {
      setDbLoading(false);
    }
  };

  const handleRollback = async (opId) => {
    if (!opId) return;
    setLoading(true);
    const lid = Date.now();
    setMessages(prev => [...prev, { id: lid, type: MSG.LOADING, timestamp: new Date() }]);
    try {
      const r = await axios.post(`${API_BASE}/query/rollback`, { operation_id: opId }, { timeout: 15000 });
      removeLoadingMsg(lid);
      if (r.data.success) {
        addMsg(MSG.ASSISTANT, `✅ ${r.data.message}`, {
          sql: r.data.rollback_sql,
          table_data: r.data.table_data,
          query_type: "ROLLBACK_RESULT",
        });
      } else {
        addMsg(MSG.ERROR, "Rollback failed", { error: r.data.error });
      }
    } catch (e) {
      removeLoadingMsg(lid);
      addMsg(MSG.ERROR, "Rollback request failed", { error: e.message });
    } finally {
      setLoading(false);
    }
  };

  const send = async () => {
    if (!selectedDB || !prompt.trim() || loading) return;
    const q = prompt.trim();
    addMsg(MSG.USER, q);
    setPrompt("");
    setLoading(true);

    const lid = Date.now();
    setMessages(prev => [...prev, { id: lid, type: MSG.LOADING, timestamp: new Date() }]);

    try {
      const r = await axios.post(`${API_BASE}/query`, {
        database: selectedDB, question: q, use_schema_context: useSchema, confirm_write: false
      }, { timeout: 45000 });

      removeLoadingMsg(lid);
      const d = r.data;

      if (d.requires_confirmation) {
        setPendingWrite({ sql: d.sql, preview: d.preview, validation: d.validation });
        return;
      }

      if (!d.success) {
        addMsg(MSG.ERROR, d.error || "Query failed", {
          sql: d.sql, error: d.error, suggestion: d.suggestion, validation: d.validation
        });
        return;
      }

      if (d.query_type === "READ") {
        addMsg(MSG.ASSISTANT, `Query returned ${d.row_count} row${d.row_count !== 1 ? "s" : ""}`, {
          sql: d.sql, query_type: "READ", validation: d.validation,
          columns: d.columns, result: d.result, row_count: d.row_count,
        });
        return;
      }

      if (d.query_type === "WRITE") {
        const verb = d.sql?.trim().split(/\s/)[0]?.toUpperCase() || "WRITE";
        addMsg(MSG.ASSISTANT, d.message || `${verb} executed`, {
          sql: d.sql, query_type: "WRITE", success: true,
          validation: d.validation,
          rows_affected: d.rows_affected,
          last_insert_id: d.last_insert_id,
          table_name: d.table_name,
          table_data: d.table_data,
          operation_id: d.operation_id,
          rollback_available: d.rollback_available,
          rollback_expires_in: d.rollback_expires_in,
          operation_verb: verb,
        });
      }
    } catch (e) {
      removeLoadingMsg(lid);
      addMsg(MSG.ERROR, "Connection error", {
        error: e.message, suggestion: `Check backend is running at ${API_BASE}`
      });
    } finally {
      setLoading(false);
    }
  };

  const confirmWrite = async () => {
    if (!pendingWrite) return;
    setLoading(true);
    const lid = Date.now();
    setPendingWrite(null);
    setMessages(prev => [...prev, { id: lid, type: MSG.LOADING, timestamp: new Date() }]);

    try {
      const r = await axios.post(`${API_BASE}/query`, {
        database: selectedDB,
        question: `[CONFIRMED] Execute: ${pendingWrite.sql}`,
        use_schema_context: useSchema,
        confirm_write: true,
      }, { timeout: 30000 });

      removeLoadingMsg(lid);
      const d = r.data;

      if (!d.success) {
        addMsg(MSG.ERROR, d.error || "Write failed", {
          sql: d.sql, error: d.error, validation: d.validation
        });
        return;
      }

      const verb = d.sql?.trim().split(/\s/)[0]?.toUpperCase() || "WRITE";
      addMsg(MSG.ASSISTANT, d.message || `${verb} executed`, {
        sql: d.sql, query_type: "WRITE", success: true,
        validation: d.validation,
        rows_affected: d.rows_affected,
        last_insert_id: d.last_insert_id,
        table_name: d.table_name,
        table_data: d.table_data,
        operation_id: d.operation_id,
        rollback_available: d.rollback_available,
        rollback_expires_in: d.rollback_expires_in,
        operation_verb: verb,
      });
    } catch (e) {
      removeLoadingMsg(lid);
      addMsg(MSG.ERROR, "Write execution failed", { error: e.message });
    } finally {
      setLoading(false);
    }
  };

  // Handle successful insert from InsertModal
  const handleInsertSuccess = (data, tableName) => {
    addMsg(MSG.ASSISTANT, `✅ Row inserted into \`${tableName}\``, {
      sql: data.sql,
      query_type: "WRITE",
      success: true,
      rows_affected: data.rows_affected,
      last_insert_id: data.last_insert_id,
      table_name: tableName,
      table_data: data.table_data,
      operation_id: data.operation_id,
      rollback_available: data.rollback_available,
      rollback_expires_in: data.rollback_expires_in,
      operation_verb: "INSERT",
    });
  };

  const clearChat = () => setMessages([{
    id: Date.now(), type: MSG.SYSTEM,
    content: "🧹 Chat cleared.",
    timestamp: new Date(),
  }]);

  const exportCSV = () => {
    const last = [...messages].reverse().find(m => m.type === MSG.ASSISTANT && m.result);
    if (!last?.columns) return alert("No results to export");
    const csv = [
      last.columns.join(","),
      ...last.result.map(row =>
        row.map(c => `"${String(c ?? "").replace(/"/g, '""')}"`).join(",")
      )
    ].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8;" }));
    a.download = `results_${new Date().toISOString().slice(0, 19).replace(/:/g,"-")}.csv`;
    a.click();
  };

  const statusColor =
    backendOk === null ? "bg-yellow-400" :
    backendOk          ? "bg-emerald-500" :
                         "bg-red-500";
  const statusText =
    backendOk === null ? "Checking..." :
    backendOk          ? "Backend Connected" :
                         "Backend Offline";

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50 to-emerald-50 flex flex-col">
      {/* ── Header ── */}
      <header className="bg-white/80 backdrop-blur-md border-b border-gray-200 sticky top-0 z-30 shadow-sm">
        <div className="max-w-6xl mx-auto px-4 py-3">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-3">
              <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-blue-600 via-emerald-500 to-teal-600 flex items-center justify-center text-lg shadow-md">
                🗄️
              </div>
              <div>
                <h1 className="text-lg font-bold text-gray-800 leading-tight">MySQL AI Assistant</h1>
                <p className="text-xs text-gray-400">Natural Language → Validate → Execute → Rollback</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <div className={cls("w-2 h-2 rounded-full animate-pulse", statusColor)} />
              <span className="text-xs text-gray-500">{statusText}</span>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={loadDatabases} disabled={dbLoading}
              className={cls(
                "flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg font-medium shadow-sm transition-all",
                dbLoading ? "bg-gray-100 text-gray-400 cursor-not-allowed" : "bg-blue-100 text-blue-700 hover:bg-blue-200"
              )}
            >
              {dbLoading ? <><span className="animate-spin">↻</span> Loading</> : <><span>📂</span> Load DBs</>}
            </button>

            <select
              value={selectedDB} onChange={e => setSelectedDB(e.target.value)}
              disabled={databases.length === 0 || dbLoading}
              className="px-3 py-1.5 text-xs border border-gray-300 rounded-lg bg-white focus:ring-2 focus:ring-blue-400 outline-none shadow-sm disabled:bg-gray-50 disabled:text-gray-400"
            >
              <option value="">{databases.length === 0 ? "Load databases first" : "Select Database"}</option>
              {databases.map(db => <option key={db} value={db}>{db}</option>)}
            </select>

            <label className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-gray-200 bg-white shadow-sm cursor-pointer hover:bg-gray-50">
              <input type="checkbox" checked={useSchema} onChange={e => setUseSchema(e.target.checked)}
                className="w-3.5 h-3.5 rounded border-gray-300 text-blue-600 focus:ring-blue-400" />
              <span className="font-medium text-gray-700">Schema Context</span>
              <span className="text-gray-300" title="Improves JOIN accuracy">💡</span>
            </label>

            <button onClick={clearChat}
              className="px-3 py-1.5 text-xs text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors">
              🧹 Clear
            </button>

            <button onClick={exportCSV}
              className="px-3 py-1.5 text-xs text-emerald-700 hover:bg-emerald-50 rounded-lg transition-colors">
              📥 Export CSV
            </button>
          </div>
        </div>
      </header>

      {loading && (
        <div className="bg-blue-50 border-b border-blue-100 px-4 py-2 text-xs text-blue-700 text-center flex items-center justify-center gap-2">
          <LoadingDots />
          <span>Generating SQL, then running Validator Agent…</span>
        </div>
      )}

      {/* ── Messages ── */}
      <main className="flex-1 overflow-y-auto px-4 py-5">
        <div className="max-w-4xl mx-auto">
          {messages.map(m => (
            <ChatBubble key={m.id} msg={m} onRollback={handleRollback} />
          ))}
          <div ref={bottomRef} />
        </div>
      </main>

      {/* ── Input ── */}
      <footer className="bg-white/80 backdrop-blur-md border-t border-gray-200 sticky bottom-0 z-20 shadow-lg">
        <div className="max-w-4xl mx-auto p-4">
          <div className="flex gap-2 items-end">

            {/* ── Insert Row Button ── */}
            <button
              onClick={() => setInsertOpen(true)}
              disabled={!selectedDB || !backendOk}
              title={!selectedDB ? "Select a database first" : "Insert a new row manually"}
              className={cls(
                "flex-shrink-0 flex items-center gap-1.5 px-3 py-3 rounded-xl text-sm font-semibold transition-all shadow-sm border",
                (!selectedDB || !backendOk)
                  ? "bg-gray-100 text-gray-300 border-gray-200 cursor-not-allowed"
                  : "bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100 hover:border-emerald-400 active:scale-95"
              )}
            >
              <span className="text-base">➕</span>
              <span className="hidden sm:inline">Insert</span>
            </button>

            <div className="flex-1 relative">
              <textarea
                ref={textareaRef}
                value={prompt}
                onChange={e => setPrompt(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                placeholder={backendOk ? "Ask about your data… e.g. Show top 5 orders by revenue" : "Waiting for backend connection…"}
                rows={1}
                disabled={loading || !backendOk}
                className="w-full px-4 py-3 pr-12 border border-gray-300 rounded-2xl text-sm focus:ring-2 focus:ring-blue-400 focus:border-blue-400 outline-none resize-none bg-white/80 shadow-sm transition-shadow hover:shadow-md disabled:bg-gray-100 disabled:text-gray-400"
                style={{ minHeight: 48, maxHeight: 120 }}
              />
              <span className="absolute right-3 bottom-3 text-[10px] text-gray-300">
                {prompt.length}/500
              </span>
            </div>

            <button
              onClick={send}
              disabled={loading || !selectedDB || !prompt.trim() || !backendOk}
              className={cls(
                "px-5 py-3 rounded-xl text-sm font-semibold text-white transition-all shadow-md hover:shadow-lg active:scale-95",
                loading || !selectedDB || !prompt.trim() || !backendOk
                  ? "bg-gray-300 cursor-not-allowed"
                  : "bg-gradient-to-r from-blue-600 via-emerald-600 to-teal-600 hover:brightness-110"
              )}
            >
              {loading
                ? <span className="flex items-center gap-1.5"><span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Thinking</span>
                : <span className="flex items-center gap-1.5">🚀 Ask</span>}
            </button>
          </div>

          <div className="flex flex-wrap items-center justify-between mt-2.5 text-[11px] text-gray-400">
            <span>
              💡 Try:{" "}
              <code className="bg-gray-100 text-gray-600 px-1 py-0.5 rounded">
                "Show top 5 orders by revenue"
              </code>
              {" "}or click{" "}
              <strong className="text-emerald-600">➕ Insert</strong>
              {" "}to add a row manually
            </span>
            <span className="hidden md:block">⌨️ Enter to send · Shift+Enter for new line</span>
          </div>
        </div>
      </footer>

      {/* ── Write Confirm Modal ── */}
      <ConfirmModal
        pending={pendingWrite}
        onConfirm={confirmWrite}
        onCancel={() => {
          setPendingWrite(null);
          addMsg(MSG.SYSTEM, "✋ Write operation cancelled");
        }}
      />

      {/* ── Insert Row Modal ── */}
      <InsertModal
        open={insertOpen}
        selectedDB={selectedDB}
        onClose={() => setInsertOpen(false)}
        onSuccess={handleInsertSuccess}
        addMsg={addMsg}
      />

      <style>{`
        @keyframes fadeSlide {
          from { opacity: 0; transform: translateY(8px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}