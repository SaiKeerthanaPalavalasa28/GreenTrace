import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { Card, ErrorBox, PageHeader, linkButtonClass } from '../components/ui'
import { formatQty } from '../components/status'
import { issueLabel } from '../components/issues'

export default function ReviewQueuePage() {
  const navigate = useNavigate()
  const [items, setItems] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => { api('/review').then(setItems).catch(setError) }, [])

  return (
    <div className="space-y-6">
      <PageHeader title="Review queue"
        subtitle="Bills land here when any validation rule fails or the model is unsure. Their emissions are not counted until a reviewer approves them. Oldest first.">
        {items?.length > 0 && (
          <button onClick={() => navigate(`/review/${items[0].bill_id}`)} className={linkButtonClass}>Start reviewing</button>
        )}
      </PageHeader>
      <ErrorBox error={error} />
      <Card title={items ? `${items.length} bill${items.length === 1 ? '' : 's'} waiting` : 'Loading…'}>
        {items?.length === 0 ? (
          <p className="text-sm text-slate-500">Nothing to review. <Link className="text-emerald-700 hover:underline" to="/upload">Upload bills</Link></p>
        ) : (
          <div className="masonry">
            {(items || []).map((i, n) => (
              <article key={i.bill_id} tabIndex={0} role="link"
                className="pin glass rise cursor-pointer rounded-3xl p-5 outline-none"
                style={{ animationDelay: `${Math.min(n, 12) * 40}ms` }}
                onClick={() => navigate(`/review/${i.bill_id}`)} onKeyDown={(e) => e.key === 'Enter' && navigate(`/review/${i.bill_id}`)}>
                <h3 className="break-words text-sm font-bold">{i.original_filename}</h3>
                <p className="text-xs text-slate-500">{i.facility_name}</p>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {i.issue_codes.map((c, k) => (
                    <span key={k} className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${i.blocking_codes.includes(c) ? 'bg-red-50 text-red-800 ring-red-200' : 'bg-amber-50 text-amber-800 ring-amber-200'}`}>
                      {issueLabel(c)}
                    </span>
                  ))}
                </div>
                <div className="mt-4 flex items-end justify-between gap-2 border-t border-slate-200/60 pt-3 text-xs text-slate-500">
                  <span>{i.billing_period_start ? `${i.billing_period_start} → ${i.billing_period_end ?? '?'}` : 'Period unknown'}</span>
                  <span className="text-sm font-semibold tabular-nums text-slate-900">{i.quantity != null ? `${formatQty(i.quantity)} ${i.unit}` : '—'}</span>
                </div>
              </article>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
