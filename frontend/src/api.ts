export async function api<T>(path:string, body?:unknown):Promise<T> {
  const response = await fetch('/api'+path, body === undefined ? {signal:AbortSignal.timeout(10000)} : {
    method:'POST', headers:{'Content-Type':'application/json','X-Deadlock-Control':'1'},body:JSON.stringify(body),signal:AbortSignal.timeout(20000)
  });
  const data = await response.json();
  if(!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'The request was rejected. Check the supplied values.');
  return data;
}
export const bytes = (value:number|null|undefined) => value == null ? '—' : value >= 1024**3 ? (value/1024**3).toFixed(1)+' GB' : (value/1024**2).toFixed(0)+' MB';
export const clock = (seconds:number) => new Date(seconds*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
export const shortPath = (path:string|undefined) => path?.replace(/^\/Users\/[^/]+/, '~').replace(/^\/home\/[^/]+/,'~') || 'Unavailable';
export const label = (value:string) => value.toLowerCase().replaceAll('_',' ').replace(/^./, c=>c.toUpperCase());
