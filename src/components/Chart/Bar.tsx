
export default function Bar({
  data, height=160
}: { data: {label:string, value:number}[]; height?:number }){
  const max = Math.max(...data.map(d=>d.value), 1)
  return (
    <svg viewBox={`0 0 500 ${height}`} className="w-full">
      <rect x="0" y="0" width="500" height={height} fill="#FAFAFA" />
      {data.map((d, i) => {
        const w = 500 / data.length - 10
        const x = 5 + i * (w + 10)
        const h = Math.max(2, (d.value / max) * (height - 30))
        const y = height - 20 - h
        return (
          <g key={i}>
            <rect x={x} y={y} width={w} height={h} fill="#3B82F6" opacity="0.9" />
            <text x={x + w/2} y={height-6} fontSize="10" textAnchor="middle" fill="#6B7280">{d.label}</text>
          </g>
        )
      })}
    </svg>
  )
}
