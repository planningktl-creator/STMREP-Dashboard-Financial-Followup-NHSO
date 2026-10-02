from repstm.parser import APPROVED_LAYOUTS,REGISTRY,VERSION,digest,validate_layout,content_digest,family

def test_all_approved_layouts_match_version_fingerprint_and_semantics():
    assert REGISTRY['version']==VERSION
    assert len(APPROVED_LAYOUTS)>=33
    for key,layout in APPROVED_LAYOUTS.items():
        assert digest(layout)==key
        assert layout['mapping_version']==VERSION
        if layout['kind']!='stm_period_summaries':
            assert validate_layout(layout['kind'],layout['width'],layout['header_paths'])

def test_same_width_with_changed_financial_header_is_rejected():
    template=next(s for s in APPROVED_LAYOUTS.values() if s['kind']=='stm_claims' and s['width']==43)
    changed=template['header_paths'].copy();changed[37]='Unrelated financial total'
    assert not validate_layout('stm_claims',43,changed)

def test_known_width_with_unknown_fingerprint_is_not_approved():
    layout=next(s for s in APPROVED_LAYOUTS.values() if s['kind']=='rep_claims').copy()
    layout['header_paths']=layout['header_paths'].copy();layout['header_paths'][-1]+=' new unreviewed field'
    assert digest(layout) not in APPROVED_LAYOUTS

def test_streamed_hash_equals_canonical_hash_for_thai_and_large_content():
    value={'ไทย':[[i,None,"O'Reilly\nภาษาไทย",'-0.0012'] for i in range(20000)],'nested':{'a':True,'b':False}}
    assert content_digest(value)==digest(value)

def test_unknown_payer_is_not_assigned_to_ucs():
    assert family('IP_APPEAL_NHSO')=='UCS'
    assert family('OPCS_APPEAL')=='OFC'
    assert family('OPSTP')=='STP'
    assert family('OP_NEW_PAYER')=='UCS'  # Standard OP report family.
    assert family('OPXYZ').startswith('UNKNOWN:')
