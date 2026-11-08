import datetime
from types import SimpleNamespace as NS

import pytest

from finops_agent.inventory import capacity_type, collect_inventory, node_payload, parse_bytes, parse_cpu


@pytest.mark.parametrize("q,cores", [("4", 4), ("500m", 0.5), ("250000000n", 0.25), ("1.5", 1.5)])
def test_parse_cpu(q, cores):
    assert parse_cpu(q) == pytest.approx(cores)


@pytest.mark.parametrize("q,b", [("16Gi", 16 * 2**30), ("16393536Ki", 16393536 * 1024), ("1G", 1e9), ("1024", 1024)])
def test_parse_bytes(q, b):
    assert parse_bytes(q) == pytest.approx(b)


@pytest.mark.parametrize("labels,expected", [
    ({"karpenter.sh/capacity-type": "spot"}, "spot"),
    ({"karpenter.sh/capacity-type": "on-demand"}, "on_demand"),
    ({"eks.amazonaws.com/capacityType": "SPOT"}, "spot"),
    ({"cloud.google.com/gke-spot": "true"}, "spot"),
    ({"kubernetes.azure.com/scalesetpriority": "spot"}, "spot"),
    ({}, "on_demand"),
])
def test_capacity_type_detection(labels, expected):
    assert capacity_type(labels) == expected


def test_node_payload_reads_cloud_labels_and_price_override():
    created = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    p = node_payload("n1", {"node.kubernetes.io/instance-type": "m5.xlarge",
                            "topology.kubernetes.io/region": "us-east-1",
                            "topology.kubernetes.io/zone": "us-east-1a", "finops.io/hourly-price": "0.15"},
                     {"cpu": "4", "memory": "16Gi"}, created)
    assert p["instance_type"] == "m5.xlarge" and p["region"] == "us-east-1"
    assert p["vcpu"] == 4 and p["memory_gib"] == pytest.approx(16)
    assert p["hourly_price"] == 0.15
    assert p["created_at"].startswith("2026-01-01")


def test_capacity_override_labels_for_simulated_clusters():
    p = node_payload("kind-worker", {"finops.io/capacity-cpu": "4", "finops.io/capacity-memory": "16Gi"},
                     {"cpu": "28", "memory": "8000Mi"}, None)
    assert (p["vcpu"], p["memory_gib"]) == (4, 16)


def _obj(ns, name, labels=None, **spec):
    return NS(metadata=NS(namespace=ns, name=name, labels=labels or {}, owner_references=spec.pop("owners", None)),
              spec=NS(replicas=spec.get("replicas")), status=NS(desired_number_scheduled=spec.get("desired")))


class FakeCore:
    def list_node(self):
        return NS(items=[NS(metadata=NS(name="n1", labels={"node.kubernetes.io/instance-type": "m5.large"},
                                        creation_timestamp=None), status=NS(capacity={"cpu": "2", "memory": "8Gi"}))])


class FakeApps:
    def list_deployment_for_all_namespaces(self):
        return NS(items=[_obj("shop", "web", {"team": "web"}, replicas=3), _obj("skip", "x", replicas=1)])

    def list_stateful_set_for_all_namespaces(self):
        return NS(items=[_obj("db", "pg", replicas=1)])

    def list_daemon_set_for_all_namespaces(self):
        return NS(items=[_obj("kube-system", "proxy", desired=3)])


class FakeBatch:
    def list_cron_job_for_all_namespaces(self):
        return NS(items=[_obj("data", "etl")])

    def list_job_for_all_namespaces(self):
        return NS(items=[_obj("data", "etl-123", owners=[NS(kind="CronJob")]), _obj("data", "migrate-once")])


def test_collect_inventory_lists_owners_and_skips_cronjob_children():
    inv = collect_inventory(FakeCore(), FakeApps(), FakeBatch(), excluded_namespaces=frozenset({"skip"}))
    assert inv["nodes"][0]["vcpu"] == 2
    kinds = {(w["kind"], w["name"]): w for w in inv["workloads"]}
    assert kinds[("Deployment", "web")]["replicas"] == 3 and kinds[("Deployment", "web")]["labels"] == {"team": "web"}
    assert kinds[("DaemonSet", "proxy")]["replicas"] == 3
    assert ("Job", "migrate-once") in kinds and ("Job", "etl-123") not in kinds
    assert ("Deployment", "x") not in kinds
