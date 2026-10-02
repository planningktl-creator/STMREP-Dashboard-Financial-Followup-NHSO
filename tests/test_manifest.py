from pathlib import Path
import yaml


def test_kubernetes_and_compose_contract():
    root=Path(__file__).resolve().parent.parent
    docs=list(yaml.safe_load_all((root/'deploy/kubernetes.yaml').read_text()))
    deployment=next(d for d in docs if d['kind']=='Deployment')
    assert deployment['spec']['replicas']==1 and deployment['spec']['strategy']['type']=='Recreate'
    pod=deployment['spec']['template']['spec'];container=pod['containers'][0]
    assert pod['terminationGracePeriodSeconds']==150
    assert container['ports'][0]['containerPort']==8000
    assert next(e['value'] for e in container['env'] if e['name']=='PORT')=='8000'
    assert container['securityContext']['readOnlyRootFilesystem']
    assert container['readinessProbe']['timeoutSeconds']>5
    assert container['resources']['requests']['cpu']==container['resources']['limits']['cpu']
    assert container['resources']['requests']['memory']==container['resources']['limits']['memory']
    temp_vol=next(v for v in pod['volumes'] if v['name']=='temporary')
    assert temp_vol['emptyDir'].get('medium','')==''
    assert temp_vol['emptyDir']['sizeLimit']=='1Gi'
    ingress=next(d for d in docs if d['kind']=='Ingress')
    assert ingress['metadata']['annotations']['nginx.ingress.kubernetes.io/enable-access-log']=='false'
    compose=yaml.safe_load((root/'compose.yaml').read_text())['services']['app']
    assert compose['read_only'] and compose['cap_drop']==['ALL'] and compose['stop_grace_period']=='150s'
    assert compose['environment']['PORT']=='8000'


def test_image_and_dependency_contract():
    root=Path(__file__).resolve().parent.parent
    docker=(root/'Dockerfile').read_text()
    assert docker.count('@sha256:')==2 and '--require-hashes' in docker
    assert 'USER 10929:10929' in docker and 'financial.server' in docker
    assert 'requirements.lock' in docker and 'HEALTHCHECK' in docker
    assert (root/'requirements.lock').read_text().count('--hash=sha256:')>20
