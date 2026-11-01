// Byte caps apply before UTF-8 decoding, JSON parsing, or shape validation.
export const EVIDENCE_JSON_LIMIT = 64 * 1024;
export const API_ERROR_JSON_LIMIT = 8 * 1024;

export async function boundedJsonResponse(response, {maxBytes=EVIDENCE_JSON_LIMIT, signal}={}) {
  const refused = message => Error(message);
  const declared = response.headers.get('Content-Length');
  const type = response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase();
  if (signal?.aborted || type !== 'application/json' || (declared !== null &&
      (!/^\d+$/.test(declared) || !Number.isSafeInteger(Number(declared)) || Number(declared)>maxBytes))) {
    try { await response.body?.cancel(); } catch { /* refusal remains authoritative */ }
    throw refused('Local JSON response is cancelled, malformed, or exceeds its byte limit.');
  }
  let reader;try{reader=response.body?.getReader?.();}catch(error){try{await response.body?.cancel?.();}catch{}throw error;}
  if (!reader){try{await response.body?.cancel?.();}catch{}throw refused('Bounded local JSON response is unavailable.');}
  const chunks=[]; let size=0, complete=false, primary=null;
  const abort=()=>{void reader.cancel().catch(()=>{});};
  signal?.addEventListener('abort', abort, {once:true});
  try {
    while (true) {
      if(signal?.aborted) throw refused('Local JSON response cancelled.');
      const {done,value}=await reader.read();
      if(signal?.aborted) throw refused('Local JSON response cancelled.');
      if(done){complete=true;break;}
      if(!(value instanceof Uint8Array) || size+value.byteLength>maxBytes)
        throw refused('Local JSON response exceeds its byte limit.');
      size+=value.byteLength; chunks.push(value);
    }
  } catch(error){primary=error;throw error;} finally {
    signal?.removeEventListener('abort', abort);
    let cleanup=null;try{if(!complete)await reader.cancel();}catch(error){cleanup=error;}
    try{reader.releaseLock();}catch(error){cleanup??=error;}if(!primary&&cleanup)throw cleanup;
  }
  if(declared!==null && Number(declared)!==size)
    throw refused('Local JSON response length is inconsistent.');
  const bytes=new Uint8Array(size);let offset=0;
  for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.byteLength;}
  const text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);
  const result=JSON.parse(text,(_key,value)=>{
    if(typeof value==='number'&&!Number.isFinite(value)) throw refused('Nonfinite local JSON response.');
    return value;
  });
  if(signal?.aborted) throw refused('Local JSON response cancelled.');
  return result;
}
