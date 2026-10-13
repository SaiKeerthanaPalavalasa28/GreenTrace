import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { Card, ErrorBox } from '../components/ui'
import { formatQty } from '../components/status'
import { issueLabel } from '../components/issues'

export default function ReviewQueuePage() {
  const navigate = useNavigate()
  const [items, setItems] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => { api('/review').then(setItems).catch(setError) }, [])

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Review queue</h1>
        {items?.length > 0 && (
          <button onClick={() => navigate(`/review/${items[0].bill_id}`)} className="rounded-md bg-emerald-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-800">
            Start reviewing
          </button>
        )}
      </div>
      <p className="max-w-3xl text-sm text-slate-600">
        Bills land here when any validation rule fails or the model is unsure. Their emissions are not
        counted until a reviewer approves them. Oldest first.
      </p>
      <ErrorBox error={error} />
      <Card title={items ? `${items.length} bill${items.length === 1 ? '' : 's'} waiting` : 'Loading…'}>
        {items?.length === 0 ? (
          <p className="text-sm text-slate-500">Nothing to review. <Link className="text-emerald-700 hover:underline" to="/upload">Upload bills</Link></p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-slate-500">
                <tr>
                  <th className="py-2 pr-4 font-medium">File</th>
                  <th className="py-2 pr-4 font-medium">Facility</th>
                  <th className="py-2 pr-4 font-medium">Period</th>
                  <th className="py-2 pr-4 text-right font-medium">Quantity</th>
                  <th className="py-2 font-medium">Issues</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {(items || []).map((i) => (
                  <tr key={i.bill_id} className="cursor-pointer align-top hover:bg-slate-50" onClick={() => navigate(`/review/${i.bill_id}`)}>
                    <td className="max-w-xs truncate py-2 pr-4 font-medium">{i.original_filename}</td>
                    <td className="py-2 pr-4">{i.facility_name}</td>
                    <td className="whitespace-nowrap py-2 pr-4 text-xs">{i.billing_period_start ? `${i.billing_period_start} → ${i.billing_period_end ?? '?'}` : '—'}</td>
                    <td className="whitespace-nowrap py-2 pr-4 text-right tabular-nums">{i.quantity != null ? `${formatQty(i.quantity)} ${i.unit}` : '—'}</td>
                    <td className="py-2">
                      <div className="flex flex-wrap gap-1">
                        {i.issue_codes.map((c, n) => (
                          <span key={n} className={`rounded px-1.5 py-0.5 text-xs ${i.blocking_codes.includes(c) ? 'bg-red-50 text-red-800' : 'bg-amber-50 text-amber-800'}`}>
                            {issueLabel(c)}
                          </span>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
