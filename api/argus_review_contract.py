"""Load the shared readiness contract from the repository's deployment bundle."""
from pathlib import Path
import sys
import os

_RUNTIME = str(Path(__file__).resolve().parents[1] / 'runtime' / 'argus-rag')
if _RUNTIME not in sys.path:
    sys.path.insert(0, _RUNTIME)
from review_readiness import active_filter, filter_hits, grounded_answer, document_readiness, missing_documents  # noqa: E402,F401


def queue_project_ingestion(target, folder):
    """Route existing Review documents to the same writer as new file drops."""
    from review_readiness import Registry
    registry = Registry()
    collection = os.environ['ARGUS_REVIEW_COLLECTION']
    library = Path(os.environ['ARGUS_RAG_LIBRARY_ROOT']).resolve()
    marked = []
    for path in Path(target).rglob('*.pdf'):
        source = path.resolve().relative_to(library).as_posix()
        if registry.request_retry(collection, source):
            marked.append(source)
    return {'folder':folder, 'queued':len(marked), 'files':marked[:40], 'status':'queued'}


def project_answer(question, project, source, *, collection, embed_fn, qd_fn):
    """Source-scoped Project Review answer using the shared readiness registry."""
    if not all(isinstance(v,str) and v.strip() for v in [question,project,source]):
        raise ValueError('Question, project and source are required')
    filt=active_filter(collection)
    filt['must'].extend([{'key':'project','match':{'value':project}}, {'key':'source','match':{'value':source}}])
    vectors=embed_fn([question])
    if len(vectors)!=1 or len(vectors[0])!=768:
        raise ValueError('Valid query embedding required')
    response=qd_fn('/collections/'+collection+'/points/search',{'vector':vectors[0],'filter':filt,'limit':20,'with_payload':True})
    hits=filter_hits(response.get('result',[]),collection)
    result=grounded_answer(question,hits)
    result['retrieval']=[{'source':h['payload']['source'],'generation':h['payload']['generation'],
                          'pdf_page':h['payload']['pdf_page'],'source_hash':h['payload']['source_hash']} for h in hits]
    return result
