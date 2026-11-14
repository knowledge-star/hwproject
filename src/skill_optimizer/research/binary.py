"""Native binary evidence indexing; original evidence remains in the execution record."""
import copy
import hashlib
import json
from .officeqa import flatten_native

def reflection_native(rows):
    """Preserve all native text/actions; archive opaque binary blocks by hash.

    Upstream reflection is text-only. Sending base64 as ordinary prose does not
    expose its pixels and can exceed the model context. Original multimodal
    records are retained unchanged; this adapter never invents visual findings.
    """
    normalized=copy.deepcopy(rows);binary=[]
    for row in normalized:
        message=row.get('message',row)
        content=message.get('content',[])
        if not isinstance(content,list):continue
        for i,block in enumerate(content):
            if not isinstance(block,dict) or block.get('type') not in ['image','image_url','audio','input_audio']:continue
            encoded=json.dumps(block,sort_keys=True,ensure_ascii=False).encode()
            item=dict(type=block['type'],sha256=hashlib.sha256(encoded).hexdigest(),serialized_bytes=len(encoded),mime_type=block.get('mimeType'))
            binary.append(item)
            content[i]=dict(type='text',text='[Native binary evidence archived unchanged in the source trajectory: '+json.dumps(item,sort_keys=True)+'. Pixels/audio are not supplied to this text-only reflection; infer no unsupported visual facts.]')
    return flatten_native(normalized),binary

