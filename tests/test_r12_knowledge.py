import json
import hashlib
from zipfile import ZipFile
import pytest

from lsprepost_mcp.knowledge import KnowledgeBase
from lsprepost_mcp.knowledge_workflow import collect_evidence
from lsprepost_mcp.keyword_checks import parse_keyword_model


def corpus(tmp_path):
    source=tmp_path/'source.txt'
    source.write_text('verified source',encoding='utf-8')
    def record(key,**changes):
        return dict(id=key,index='I_model',solver='R12',case_families=['shell_plate'],
                    title='*MAT_ELASTIC',aliases=['弹性材料'],summary='弹性材料参数',
                    admitted=True,source=dict(path=str(source),sha256=hashlib.sha256(source.read_bytes()).hexdigest(),locator='PDF 1'),**changes)
    a=record('elastic')
    b={**a,'id':'wrong_version','solver':'R13'}
    c={**a,'id':'building','case_families':['large_building']}
    d={**a,'id':'unreviewed','admitted':False}
    path=tmp_path/'records.json'
    path.write_text(json.dumps({'records':[a,b,c,d]}),encoding='utf-8')
    return path,source


def test_version_scope_and_admission(tmp_path):
    path,_=corpus(tmp_path)
    assert [r['id'] for r in KnowledgeBase(path).search('弹性材料',index='I_model')]==['elastic']


def test_knowledge_dashboard_counts_and_prepost_pdf_links():
    from lsprepost_mcp.web.knowledge_api import dashboard_payload, manual_response
    from lsprepost_mcp.web.http_utils import ApiError

    data = dashboard_payload()
    assert sum(index['count'] for index in data['indexes']) == len(data['records'])
    records = {item['id']: item for item in data['records']}
    assert len(records) == len(data['records'])
    assert 'path' not in records['supp.prepost_history']
    manuals = {item['file']: item for item in data['manuals']}
    for record_id, filename, route, page in [
        ('supp.prepost_history', 'ls-prepost-tutorial.pdf', 'prepost-tutorial.pdf', 62),
        ('supp.lspost_cfile', 'lspost.pdf', 'lspost.pdf', 18),
    ]:
        if manuals[filename]['available']:
            assert records[record_id]['pdf_url'] == f'/api/knowledge/{route}#page={page}'
            status, headers, contents = manual_response(route)
            assert status == 200 and headers['Content-Type'] == 'application/pdf' and contents.startswith(b'%PDF-')
        else:
            assert records[record_id]['pdf_url'] is None
            with pytest.raises(ApiError, match='找不到|哈希'):
                manual_response(route)
    assert manual_response('../lspost.pdf') is None


def test_unknown_and_large_building_queries_return_no_reference(tmp_path):
    path,_=corpus(tmp_path)
    kb=KnowledgeBase(path)
    assert kb.search('quantum unrelated',index='I_model')==[]
    assert kb.search('弹性材料',index='I_model',case_family='large_building')==[]


def test_changed_source_is_rejected(tmp_path):
    path,source=corpus(tmp_path)
    source.write_text('tampered',encoding='utf-8')
    with pytest.raises(ValueError,match='source changed'):
        KnowledgeBase(path).search('*MAT_ELASTIC',index='I_model')


def test_stage_isolation_and_citation(tmp_path):
    path,_=corpus(tmp_path)
    kb=KnowledgeBase(path)
    assert kb.search('*MAT_ELASTIC',index='I_run')==[]
    result=kb.search('*MAT_ELASTIC',index='I_model')[0]
    assert result['source']['locator']=='PDF 1'
    assert result['title']=='*MAT_ELASTIC'


def test_invalid_index_and_limit(tmp_path):
    path,_=corpus(tmp_path)
    kb=KnowledgeBase(path)
    with pytest.raises(ValueError):kb.search('elastic',index='wrong')
    with pytest.raises(ValueError):kb.search('elastic',index='I_model',limit=0)


def test_stage_route_and_domain_scope(tmp_path):
    path, _ = corpus(tmp_path)
    kb = KnowledgeBase(path)
    assert kb.retrieve('弹性材料', stage='input_writer')['selected']['id'] == 'elastic'
    assert kb.retrieve('弹性材料', stage='runner')['status'] == 'no_applicable_reference'
    assert kb.retrieve('弹性材料', stage='input_writer', domain='blast')['candidates'] == []
    assert kb.search('用R13查询*MAT_ELASTIC', index='I_model') == []
    assert kb.search('*MAT_ELASTIC_FAKE', index='I_model') == []


def test_support_constraints_filter_before_semantic_ranking():
    eligible = []

    def dense(index, query, ids):
        eligible.append(ids)
        return {key: 0.99 for key in ids}

    kb = KnowledgeBase(vector_search=dense)
    query = '用实体单元对方板求固有频率，要求四边完全固支，边缘不得转动'
    missing = collect_evidence(kb, query, case_family='solid_plate')
    assert missing['case_id'] is None and len(missing['stages']) == 1
    assert missing['stages'][0]['requested_support'] == ['four_edges_clamped']
    assert missing['stages'][0]['requested_elements'] == ['solid']
    assert missing['stages'][0]['support_reference']['id'] == 'r12.boundary_spc_set'
    assert collect_evidence(kb, query)['case_id'] is None
    assert collect_evidence(kb, f'R13 {query}')['stages'][0]['support_reference'] is None
    assert not eligible

    result = kb.retrieve('实体方板固有频率，四边简支', stage='architect', case_family='solid_plate',
                         analysis='implicit')
    assert result['selected']['id'] == 'ansys.example_12'
    assert eligible[-1] == {'ansys.example_12'}
    assert kb.search('边界条件', index='I_model', case_id='ansys.example_12', support='four_edges_clamped') == []
    assert kb.search('*BOUNDARY_SPC_SET', index='I_model', case_family='solid_plate')
    assert kb.search('实体方板模态，四边简支而非四边固支', index='I_case', case_family='solid_plate')[0]['id'] == 'ansys.example_12'
    assert kb.search('实体方板四边简支且四边固支', index='I_case', case_family='solid_plate') == []
    assert kb.search('实体方板四边固支', index='I_case', support='four_edges_simply_supported') == []
    assert kb.search('环形板四边简支', index='I_case', case_family='general') == []


def test_four_edges_clamped_reference_covers_perimeter_and_workflow():
    kb = KnowledgeBase()
    case_id = 'project.square_shell_four_edges_clamped'
    bundle = collect_evidence(kb, '薄壳方板，四周固定，求固有频率', case_family='shell_plate',
                              analysis='implicit', support='four_edges_clamped')
    assert bundle['case_id'] == case_id
    assert len(bundle['stages']) == 6 and all(stage['status'] == 'matched' for stage in bundle['stages'])
    assert kb.retrieve('四边固支薄壳方板', stage='architect')['selected']['id'] == case_id
    deck = kb.context(case_id)['payload']['text']
    model = parse_keyword_model(deck)
    xmin, xmax = min(p[0] for p in model.nodes.values()), max(p[0] for p in model.nodes.values())
    ymin, ymax = min(p[1] for p in model.nodes.values()), max(p[1] for p in model.nodes.values())
    boundary = {nid for nid, (x, y, _) in model.nodes.items() if x in (xmin, xmax) or y in (ymin, ymax)}
    assert len(model.nodes) == 49 and len(model.shell_elements) == 36
    assert len(model.node_sets[1]) == len(boundary) == 24 and set(model.node_sets[1]) == boundary
    assert model.boundary_spc_constraints == [(1, 1, 1, 1, 1, 1, 1)]
    selected = kb.by_id[case_id]
    assert selected['r12_execution'] == 'unverified'
    for case in [item for item in kb.records if item.get('deck')]:
        label = case['applicability']
        assert label['support'] and label['geometry'] and label['element'] and label['excitation']
        assert kb.context(label['evidence_id'])['payload']['case_id'] == case['id']


def test_official_case_links_and_preserves_original_card():
    kb = KnowledgeBase()
    result = kb.retrieve('方板瞬态受压', stage='architect')
    case = result['selected']
    assert case['id'] == 'ansys.example_15'
    assert case['r12_execution'] == 'unverified'
    assert any(item['id'] == 'r12.load_segment' for item in result['related'])
    assert kb.retrieve('方板瞬态受压', stage='architect', analysis='explicit')['selected'] is None

    archive_path = kb.base / case['source']['path']
    with ZipFile(archive_path) as archive:
        original = archive.read(case['deck']['member']).decode(case['deck']['encoding'])
    lines = original.splitlines(keepends=True)
    context = kb.context(case['id'], keyword='*LOAD_SEGMENT')['payload']
    assert context['blocks']
    for block in context['blocks']:
        assert block['text'].splitlines()[0].strip() == '*LOAD_SEGMENT'
        assert block['text'] == ''.join(lines[block['start_line'] - 1:block['end_line']])


def test_manual_alias_retrieves_definition_page():
    kb = KnowledgeBase()
    hit = kb.retrieve('*MAT_001', stage='input_writer')['selected']
    assert hit['id'] == 'r12.mat_elastic'
    context = kb.context(hit['id'], page=190)['payload']
    assert [entry['pdf_page'] for entry in context['pages']] == [190]
    assert '*MAT_ELASTIC' in context['pages'][0]['text']
    with pytest.raises(ValueError, match='outside'):
        kb.context(hit['id'], page=189)


def test_manual_retrieval_uses_case_keyword_evidence():
    kb = KnowledgeBase()
    assert kb.search('*SECTION_TSHELL', index='I_model', case_family='beam_bar') == []
    assert kb.search('*SECTION_TSHELL', index='I_model', case_family='thick_shell_plate')[0]['id'] == 'r12.section_tshell'


def test_supplement_requires_explicit_scope_and_honors_document_version():
    kb = KnowledgeBase()
    if any(not (kb.base / kb.by_id[key]['source']['path']).is_file() for key in ('supp.r13_shell', 'supp.r11_shell')):
        pytest.skip('requires optional local R11 and R13 supplements')
    assert kb.search('R13 *SECTION_SHELL', index='I_model') == []
    assert [r['id'] for r in kb.search('*SECTION_SHELL', index='I_model')] == ['r12.section_shell']
    result = kb.retrieve('R13 *SECTION_SHELL', stage='input_writer', collection='supplement')
    assert [r['id'] for r in result['candidates']] == ['supp.r13_shell']
    assert result['selected']['runtime_admitted'] is False
    assert [r['id'] for r in result['related']] == ['r12.section_shell']
    r11 = kb.search('*SECTION_SHELL', index='I_model', collection='supplement', source_release='R11')
    assert [r['id'] for r in r11] == ['supp.r11_shell']
    context = kb.context(result['selected']['id'], page=3350)
    assert context['collection'] == 'supplement'
    assert 'MISC' in context['payload']['pages'][0]['text']


def test_every_audited_document_has_supplement_topics_and_text_locator():
    kb = KnowledgeBase()
    curated = json.loads(kb.path.with_name('desktop_manual_topics.json').read_text(encoding='utf-8'))
    records = [r for r in kb.records if r.get('collection') == 'supplement' and r['source'].get('filename') in curated]
    assert {r['source']['filename'] for r in records} == set(curated)
    assert all(r['reference_only'] and not r['runtime_admitted'] for r in records)
    if not (kb.base / kb.by_id['supp.r11_release']['source']['path']).is_file():
        return
    excerpt = kb.context('supp.r11_release')['payload']
    assert 'R11.0.0' in excerpt['text']
    assert excerpt['start_line'] == 1


def test_case_recipes_are_linked_and_retrieve_exact_boundary_evidence():
    kb = KnowledgeBase()
    cases = [record for record in kb.records if record.get('deck')]
    for case in cases:
        recipes = [kb.by_id[item['id']] for item in kb.references(case['id']) if item['id'].startswith('guide.')]
        assert {r['recipe']['topic'] for r in recipes} == {'boundary', 'loading', 'output'}

    result = kb.retrieve('边界条件', stage='input_writer', case_id='ansys.example_15')
    assert result['selected']['id'] == 'guide.example_15.boundary'
    payload = kb.context(result['selected']['id'])['payload']
    assert payload['r12_execution'] == 'unverified'
    assert {b['keyword'] for b in payload['blocks']} == {'*SET_NODE_LIST', '*BOUNDARY_SPC_SET', '*NODE'}
    original = kb.context('ansys.example_15', keyword='*SET_NODE_LIST')['payload']['blocks']
    assert payload['blocks'][0] == original[1]
    assert kb.retrieve('边界条件', stage='input_writer', case_id='ansys.example_15', case_family='beam_bar')['selected'] is None
    assert kb.search('边界条件', index='I_model', case_id='ansys.example_15')[0]['id'] == result['selected']['id']
    explicit = kb.search('厚壳方板边界', index='I_model', case_family='general', analysis='explicit')
    assert all(r.get('analysis') == 'explicit' for r in explicit if r.get('recipe'))

    for case in ('ansys.example_14', 'ansys.example_15'):
        node_rows = kb.context(case, keyword='*NODE')['payload']['blocks'][0]['text'].splitlines()
        tc3 = {int(line[:8]) for line in node_rows if line[56:64].strip() == '3' and not line.startswith('$')}
        node_set = kb.context(case, keyword='*SET_NODE_LIST')['payload']['blocks'][1]['text']
        set_rows = [line for line in node_set.splitlines()[1:] if line.strip() and not line.startswith('$')]
        members = {int(node) for line in set_rows[1:] for node in line.split()}
        assert tc3 == members and len(members) == 32


def test_open_fixture_evidence_and_prepost_tutorial_provenance():
    kb = KnowledgeBase()
    query = '单壳单元部件依赖'
    fixture = kb.retrieve(query, stage='input_writer', collection='supplement')['selected']
    assert fixture['id'] == 'open.pydyna.shell_closure'
    assert not fixture['runtime_admitted']
    assert fixture['supporting_sources'][0]['locator'] == 'upstream license'
    assert fixture['id'] not in {r['id'] for r in kb.search(query, index='I_model')}
    excerpt = kb.context(fixture['id'])['payload']
    assert excerpt['text'].startswith('*PART')
    assert '*ELEMENT_SHELL' in excerpt['text'] and excerpt['checks']

    guide = kb.retrieve('PrePost设置边界条件', stage='visualization', collection='supplement')
    assert guide['selected']['id'] == 'prepost.spc'
    assert guide['selected']['source']['url'] == 'https://lsdyna.ansys.com/p5-spc1/'
    assert guide['selected']['source']['license_status'].startswith('public Ansys')
    assert 'guide.example_15.boundary' in {item['id'] for item in guide['related']}


def test_workflow_keeps_case_context_and_stops_on_no_reference():
    kb = KnowledgeBase()
    result = collect_evidence(kb, '建一个简支厚壳方板，输出板心位移时程',
                              case_family='thick_shell_plate', analysis='implicit_transient')
    assert result['case_id'] == 'ansys.example_15'
    assert [s['stage'] for s in result['stages']] == [
        'architect', 'meshing', 'input_writer', 'runner', 'reviewer', 'visualization']
    assert {s['case_id'] for s in result['stages'][1:]} == {result['case_id']}
    writer = result['stages'][2]
    assert {item['payload']['topic'] for item in writer['evidence']} == {'boundary', 'loading', 'output'}
    assert any(item['record_id'] == 'r12.boundary_spc_set' for item in writer['manual_definitions'])
    assert result['stages'][3]['tools']
    miss = collect_evidence(kb, '量子化学轨道')
    assert miss['case_id'] is None and len(miss['stages']) == 1


def test_dense_candidates_respect_case_and_exact_card_path():
    calls = []

    def semantic(index, query, eligible):
        calls.append((index, eligible))
        return {'guide.example_14.boundary': 0.99, 'guide.example_15.boundary': 0.9}

    kb = KnowledgeBase(vector_search=semantic)
    matches = kb.search('支承限制', index='I_model', case_id='ansys.example_15')
    assert matches[0]['id'] == 'guide.example_15.boundary'
    assert 'guide.example_14.boundary' not in calls[0][1]
    exact = kb.search('*BOUNDARY_SPC_SET', index='I_model', case_id='ansys.example_15')
    assert [r['id'] for r in exact] == ['r12.boundary_spc_set'] and len(calls) == 1
