import { MapContainer, TileLayer, Marker, Popup, Polyline } from 'react-leaflet'
import L from 'leaflet'
import type { LatLngExpression } from 'leaflet'

const depotIcon = new L.DivIcon({ className:'depot-marker', html:'<span>◆</span>', iconSize:[28,28], iconAnchor:[14,14] })
const orderIcon = new L.DivIcon({ className:'order-marker', html:'<span>●</span>', iconSize:[20,20], iconAnchor:[10,10] })
export default function RouteMap({ depots=[], routes=[] }:{depots:any[],routes:any[]}) {
  const center:LatLngExpression = [17.42,78.43]
  return <div className="map-wrap"><MapContainer center={center} zoom={11} scrollWheelZoom className="map">
    <TileLayer attribution='&copy; OpenStreetMap contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"/>
    {depots.map(d=><Marker key={d.id} position={[d.lat,d.lng]} icon={depotIcon}><Popup><b>{d.name}</b><br/>Depot</Popup></Marker>)}
    {routes.flatMap((r:any)=>
      [<Marker key={`${r.id}-depot`} position={[r.depot.lat,r.depot.lng]} icon={depotIcon}><Popup>{r.depot.name} · {r.vehicle.name}</Popup></Marker>,
       ...r.stops.map((s:any)=><Marker key={`${r.id}-${s.order_id}`} position={[s.lat,s.lng]} icon={orderIcon}><Popup><b>{s.customer}</b><br/>Order {s.order_id}<br/>Risk: {s.risk.level}</Popup></Marker>),
       <Polyline key={`${r.id}-line`} positions={[[r.depot.lat,r.depot.lng],...r.stops.map((s:any)=>[s.lat,s.lng] as LatLngExpression)]} pathOptions={{color:['#24d6bd','#7b8cff','#ffb454','#f16c83'][Number(r.id.slice(-1))%4],weight:4,opacity:.85}}/>]
    )}
  </MapContainer><div className="map-note">Stops are connected in optimized order. Distances and ETAs come from OSRM road routing when reachable; lines are straight segments, not road geometry.</div></div>
}
