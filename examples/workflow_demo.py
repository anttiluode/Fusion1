from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fusion1 import Conductor, NodeSpec


runtime = Conductor()
runtime.register_source("code", "commit-A")
runtime.register_source("docs", "docs-A")

runtime.register_node(NodeSpec(
    "tests",
    lambda d: f"tests-pass-for:{d['code']}",
    dependencies=("code",),
    compute_cost=20,
))
runtime.register_node(NodeSpec(
    "docs_build",
    lambda d: f"docs-pass-for:{d['docs']}",
    dependencies=("docs",),
    compute_cost=8,
))
runtime.register_node(NodeSpec(
    "publish_ready",
    lambda d: d["tests"].startswith("tests-pass") and d["docs_build"].startswith("docs-pass"),
    dependencies=("tests", "docs_build"),
    compute_cost=1,
))

print(runtime.resolve("publish_ready", now=0))
print(runtime.resolve("publish_ready", now=1))

runtime.update_source("code", "commit-B", now=2)
print(runtime.resolve("publish_ready", now=2))
print(runtime.metrics())
