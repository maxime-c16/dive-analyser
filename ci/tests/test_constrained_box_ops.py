"""Tests for constrained-host deployment and proxy tuning invariants."""
import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ConstrainedBoxOpsTest(unittest.TestCase):
    def test_postgres_hdd_tuning_and_cpu_priority(self):
        compose = (ROOT / "docker-compose.yml").read_text()
        self.assertIn("wal_compression=zstd", compose)
        self.assertIn("checkpoint_timeout=15min", compose)
        self.assertIn("checkpoint_completion_target=0.9", compose)
        self.assertIn("synchronous_commit=off", compose)
        self.assertIn("image: dive-analyser-backend:latest", compose)
        self.assertGreaterEqual(compose.count("cpu_shares: 1536"), 2)

    def test_funnel_session_cache_requires_cookie_and_only_caches_200(self):
        main_conf = (ROOT / "ops/tailscale/main.conf").read_text()
        nginx_conf = (ROOT / "ops/tailscale/nginx.conf").read_text()
        self.assertIn("keys_zone=funnel_auth:", main_conf)
        self.assertRegex(
            nginx_conf,
            r'map\s+\$cookie_da_session\s+\$funnel_no_session_cache\s*\{[^}]*""\s+1;',
        )
        block_match = re.search(
            r"location\s*=\s*/_funnel_session\s*\{([^}]*)\}", nginx_conf
        )
        self.assertIsNotNone(block_match, "/_funnel_session block missing")
        block = block_match.group(1)
        self.assertIn("proxy_cache funnel_auth;", block)
        self.assertIn('proxy_cache_key "$http_host|$cookie_da_session";', block)
        self.assertIn("proxy_cache_valid 200 5s;", block)
        self.assertIn("proxy_cache_bypass $funnel_no_session_cache;", block)
        self.assertIn("proxy_no_cache $funnel_no_session_cache;", block)
        self.assertIn("proxy_ignore_headers Cache-Control Expires;", block)
        # Never cache 401/403/5xx or ignore Set-Cookie.
        self.assertNotIn("Set-Cookie", block)
        self.assertNotRegex(block, r"proxy_cache_valid\s+401")

    def test_media_migration_timer_backed_off(self):
        timer = (ROOT / "ops/systemd/dive-media-migration.timer").read_text()
        self.assertIn("OnUnitInactiveSec=10min", timer)
        self.assertNotIn("OnUnitInactiveSec=1min", timer)

    def test_release_workflow_pushes_ghcr_before_tagging(self):
        wf = (ROOT / ".github/workflows/release.yml").read_text()
        self.assertIn("packages: write", wf)
        self.assertIn("dive-analyser-frontend:sha-${{ github.sha }}", wf)
        self.assertIn("dive-analyser-backend:sha-${{ github.sha }}", wf)
        self.assertLess(
            wf.index("Build and push backend image"),
            wf.index("Tag and publish release"),
            "GHCR images must be pushed before the release tag triggers auto-deploy",
        )

    def test_deploy_dry_run_mentions_ghcr_pull_and_local_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Fake clean git repo pointing at this tree's compose file.
            repo = Path(tmp) / "repo"
            repo.mkdir()
            (repo / "docker-compose.yml").write_text("services: {}\n")
            subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)
            # Shim docker so dry-run works even without a Docker daemon.
            shim_dir = Path(tmp) / "bin"
            shim_dir.mkdir()
            docker_shim = shim_dir / "docker"
            docker_shim.write_text("#!/bin/sh\nexit 0\n")
            docker_shim.chmod(docker_shim.stat().st_mode | stat.S_IEXEC)
            env = {
                **os.environ,
                "PATH": f"{shim_dir}:{os.environ.get('PATH', '')}",
                "DIVE_SOURCE_ROOT": str(repo),
                "DIVE_DEPLOY_ROOT": str(repo),
            }
            res = subprocess.run(
                ["bash", str(ROOT / "ci/deploy.sh"), "--skip-gate", "--dry-run"],
                env=env,
                capture_output=True,
                text=True,
            )
            combined = res.stdout + res.stderr
            self.assertEqual(res.returncode, 0, combined)
            self.assertIn("ghcr.io/maxime-c16/dive-analyser-frontend:sha-", combined)
            self.assertIn("ghcr.io/maxime-c16/dive-analyser-backend:sha-", combined)
            self.assertIn("fallback: docker build", combined)


if __name__ == "__main__":
    unittest.main()
