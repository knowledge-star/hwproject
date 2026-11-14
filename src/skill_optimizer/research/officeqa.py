"""Extracted current OfficeQA algorithm. See PROVENANCE.json for source ranges."""
import copy
import hashlib
import json
import re
import threading
from pathlib import Path
from ..storage import dump, sha

CARD_SYSTEM = '''You are the SkillOpt trajectory analyst, extending a reusable OfficeQA skill memory.
Study the full tool trajectory, question and hidden TRAIN reference. Diagnose actual evidence,
table alignment, arithmetic, statistical conventions or answer-schema errors. A reference may
be inconsistent: never teach an arbitrary workaround to reproduce a reference. Extract only
generalizable procedures that follow evidence and stated question semantics. Do not include
task IDs, source filenames, years, task-specific entities, observed values, questions or answers
inside rules. Generic arithmetic constants like 100 or 0.5 are allowed.
Produce at most the given edit budget of atomically reusable skills. Each skill has an explicit
trigger (question words), procedure and failure boundary. Prefer executable evidence-slot and
operator contracts, not generic exhortations. Existing reliable rules should be preserved.
Reply ONLY JSON: {"patch":{"reasoning":"...","edits":[{"op":"append","content":"JSON_STRING"}]}}.
JSON_STRING must itself encode {"title":"short general title","trigger":["keyword","phrase"],
"body":"Specific transferable evidence checks and calculation recipe, including when not to apply.",
"required_operations":["sum"]}. Choose required_operations from lookup,sum,mean,median,
percent_change,percent_difference,share,ratio,correlation,percentile,linear_trend,expression.
If no supported improvement is justified, return zero edits. Do not output question-specific
few-shot examples, copied values, final answers or source names. Report uncertainty honestly.'''


def flatten_native(rows):
    """Preserve native text, reasoning, tool calls and results for upstream reflector."""
    # Native compaction forks copy their parent's messages into child JSONLs.
    # Deduplicate persistent message identities, not content: real repeated tool
    # outcomes with different IDs must remain visible to the analyst.
    unique=[]; seen=set()
    for row in rows:
        identity=(row.get('id'),row.get('timestamp')) if row.get('id') else None
        if identity is not None:
            if identity in seen: continue
            seen.add(identity)
        unique.append(row)
    if unique and all(r.get('timestamp') for r in unique):
        unique.sort(key=lambda r:r['timestamp'])
    out=[]
    for row in unique:
        m=row.get('message',row)
        role=m.get('role','agent')
        content=m.get('content','')
        if isinstance(content,str):
            out.append(dict(role=role,content=content)); continue
        parts=[]
        for block in content or []:
            kind=block.get('type','') if isinstance(block,dict) else ''
            if kind in ('toolCall','tool_call'):
                parts.append('[tool_call] '+json.dumps(block,ensure_ascii=False))
            elif kind in ('text','thinking'):
                parts.append(str(block.get('text',block.get('thinking',''))))
            else: parts.append(json.dumps(block,ensure_ascii=False))
        out.append(dict(role=role,content='\n'.join(parts)))
    return out


def sanitize_card(card):
    if not isinstance(card,dict): return None,'not_object'
    if not isinstance(card.get('trigger'),list) or not card['trigger']: return None,'missing_trigger'
    title=str(card.get('title','')).strip(); body=str(card.get('body','')).strip()
    if not title or not body: return None,'empty_rule'
    raw=title+' '+body+' '+' '.join(str(t) for t in card['trigger'])
    if re.search(r'UID\d+|treasury_bulletin|\b(?:19|20)\d{2}\b|\b\d{4,}\b',raw,re.I):
        return None,'task_specific_identifier_or_value'
    if len(body)>3500: return None,'overlong_rule'
    triggers=[str(t).lower().strip() for t in card['trigger'] if str(t).strip()]
    if not triggers or any(t!='*' and not re.search(r'[^\W\d_]',t) for t in triggers):
        return None,'missing_lexical_trigger'
    normalized=dict(title=title,body=body,trigger=triggers,
        required_operations=card.get('required_operations',[]))
    return normalized,''


class ReflectionRecoveryError(RuntimeError):
    """Preserve a paid response and stop rather than inventing or resampling it."""


_CARD_FIELDS = {'title', 'trigger', 'body', 'required_operations'}


_OPERATIONS = {'lookup','sum','mean','median','percent_change','percent_difference',
               'share','ratio','correlation','percentile','linear_trend','expression'}


_FUSED_APPEND = re.compile(r'(?<=\})\s*,\s*\{\s*"op"\s*:\s*"append"\s*,\s*"content"\s*:\s*"\s*(?=\{)')


def _syntax_text(text):
    """Normalize JSON string escapes only, for source-substring provenance checks."""
    text = re.sub(r'\\+u([0-9a-fA-F]{4})', lambda m: chr(int(m[1],16)), text)
    text = re.sub(r'\\+(["\\/])', lambda m: m[1], text)
    return re.sub(r'\\+([nrt])', lambda m: {'n':'\n','r':'\r','t':'\t'}[m[1]], text)


def _repair(text, scope, repairs):
    from json_repair import repair_json
    value, log = repair_json(text, return_objects=True, logging=True)
    repairs.append(dict(scope=scope, input_sha256=hashlib.sha256(text.encode()).hexdigest(),
                        syntax_changes=log))
    return value


def _validate_card(card, original, operations=None):
    if not isinstance(card,dict) or set(card) != _CARD_FIELDS:
        raise ReflectionRecoveryError('Card must contain exactly title, trigger, body and required_operations')
    if any(not isinstance(card[key],str) or not card[key].strip() for key in ('title','body')):
        raise ReflectionRecoveryError('Card title/body must be explicit nonempty strings')
    if not isinstance(card['trigger'],list) or not card['trigger'] or any(not isinstance(v,str) or not v.strip() for v in card['trigger']):
        raise ReflectionRecoveryError('Card trigger must be an explicit nonempty string array')
    if not isinstance(card['required_operations'],list) or any(v not in (_OPERATIONS if operations is None else operations) for v in card['required_operations']):
        raise ReflectionRecoveryError('Card required_operations must be an explicit supported-operation array')
    source = _syntax_text(original)
    for value in [card['title'],card['body'],*card['trigger'],*card['required_operations']]:
        if _syntax_text(value) not in source:
            raise ReflectionRecoveryError('Syntax repair changed/introduced card text absent from the original response')
    return card


class AuditedReflectionParser:
    """Upstream parser first; syntax-only recovery with immutable response copies.

    A known malformed double-encoded append sequence is separated only where
    the response itself explicitly contains its append/content delimiters.
    Every recovered card and every operator must already occur in that response.
    """
    def __init__(self, folder, upstream_extract, operations=None):
        self.folder=Path(folder); self.upstream_extract=upstream_extract
        self.operations = operations
        self.lock=threading.Lock()

    def __call__(self,text):
        if not isinstance(text,str) or not text.strip():
            raise ReflectionRecoveryError('Reflection response must be nonempty text')
        digest=hashlib.sha256(text.encode()).hexdigest()
        folder=self.folder/digest
        audit=dict(response_sha256=digest,raw_response_path=str(folder/'response.txt'),
                   parser='upstream_first_then_syntax_only_recovery',repairs=[],status='rejected')
        try:
            stripped=text.strip()
            fences=re.findall(r'```(?:json)?\s*(.*?)```',stripped,re.S)
            if len(fences)>1:
                raise ReflectionRecoveryError('Ambiguous multiple fenced reflection objects')
            candidate=fences[0].strip() if fences else stripped
            try:
                _,end=json.JSONDecoder().raw_decode(candidate)
            except ValueError:
                pass
            else:
                if candidate[end:].strip():
                    raise ReflectionRecoveryError('Ambiguous multiple reflection objects or trailing non-JSON content')
            result=self.upstream_extract(text)
            audit['upstream_returned_object']=isinstance(result,dict)
            if not isinstance(result,dict):
                if not (candidate.startswith('{') and candidate.endswith('}')):
                    raise ReflectionRecoveryError('Reflection is not one complete intended JSON object')
                result=_repair(candidate,'outer',audit['repairs'])
            if not isinstance(result,dict) or not isinstance(result.get('patch'),dict):
                raise ReflectionRecoveryError('Reflection must contain one patch object')
            result=copy.deepcopy(result)
            edits=result['patch'].get('edits')
            if not isinstance(edits,list):
                raise ReflectionRecoveryError('patch.edits must be an explicit array, including legal []')
            normalized=[]
            for index,edit in enumerate(edits):
                if not isinstance(edit,dict) or edit.get('op')!='append' or 'content' not in edit:
                    raise ReflectionRecoveryError('Every reflection edit must explicitly be append with card content')
                content=edit['content']
                if isinstance(content,dict):
                    pieces=[content]
                elif isinstance(content,str):
                    try:
                        pieces=[json.loads(content)]
                    except ValueError:
                        fragments=_FUSED_APPEND.split(content)
                        if len(fragments)>1:
                            audit['repairs'].append(dict(scope=f'edit_{index}',
                                action='separate_explicit_append_delimiters_swallowed_by_outer_string',
                                original_content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                                recovered_cards=len(fragments)))
                        pieces=[]
                        for part_index,fragment in enumerate(fragments):
                            try: value=json.loads(fragment)
                            except ValueError: value=_repair(fragment,f'edit_{index}_card_{part_index}',audit['repairs'])
                            pieces.append(value)
                else:
                    raise ReflectionRecoveryError('Edit content must encode an explicit card object')
                for card in pieces:
                    _validate_card(card,text,self.operations)
                    normalized.append(dict(op='append',content=json.dumps(card,ensure_ascii=False,sort_keys=True)))
            operations=re.findall(r'"op"\s*:\s*"([^"]+)"',_syntax_text(text))
            if operations != ['append']*len(normalized):
                raise ReflectionRecoveryError('Recovered append count/operators disagree with explicit original response')
            result['patch']['edits']=normalized
            audit.update(status='validated',edit_count=len(normalized),
                         normalized_patch_sha256=hashlib.sha256(json.dumps(result,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
                         semantic_content_generated=False)
            return result
        except Exception as exc:
            audit['error']=f'{type(exc).__name__}: {exc}'
            raise
        finally:
            with self.lock:
                folder.mkdir(parents=True,exist_ok=True)
                raw=folder/'response.txt'
                if raw.exists():
                    if sha(raw)!=digest: raise ReflectionRecoveryError('Immutable parser response copy changed')
                else: raw.write_text(text,encoding='utf-8')
                dump(folder/'parse-audit.json',audit)

