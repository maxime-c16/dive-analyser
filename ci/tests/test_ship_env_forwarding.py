"""D2 deploy plumbing: REQUIRE flag reaches Compose without secrets."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ShipEnvForwardingTests(unittest.TestCase):
    def test_compose_forwards_require_flag_default_false(self):
        import yaml

        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
        env = compose["services"]["backend"]["environment"]
        if isinstance(env, dict):
            value = env.get("MEDIA_JOBS_REQUIRE_LEASE_TOKEN")
        else:
            matches = [e for e in env if str(e).startswith("MEDIA_JOBS_REQUIRE_LEASE_TOKEN")]
            self.assertEqual(len(matches), 1, "REQUIRE flag missing from backend env")
            value = matches[0].split("=", 1)[1] if "=" in matches[0] else ""
        self.assertIn("MEDIA_JOBS_REQUIRE_LEASE_TOKEN", value or "MEDIA_JOBS_REQUIRE_LEASE_TOKEN")
        text = (ROOT / "docker-compose.yml").read_text()
        self.assertIn("MEDIA_JOBS_REQUIRE_LEASE_TOKEN: \"${MEDIA_JOBS_REQUIRE_LEASE_TOKEN:-false}\"", text)

    def test_ship_sources_managed_env_without_echoing_secrets(self):
        script = (ROOT / "ci/ship.sh").read_text()
        self.assertIn("$HOME/.config/diveanalyzer/media-jobs.env", script)
        self.assertIn('MEDIA_JOBS_ENV="$HOME/.config/diveanalyzer/media-jobs.env"', script)
        # Never echo or trace the sourced values.
        for line in script.splitlines():
            low = line.strip()
            if "MEDIA_JOBS_REQUIRE_LEASE_TOKEN" in low and ("echo" in low or "trace" in low.lower()):
                self.fail(f"secret may be echoed: {line!r}")
        # Same-SHA skip path advertises --force (env changes need it).
        self.assertIn("--force to redeploy", script)

    def test_no_managed_env_file_committed_and_no_literal_secret(self):
        self.assertFalse((ROOT / ".config/diveanalyzer/media-jobs.env").exists())
        compose_text = (ROOT / "docker-compose.yml").read_text()
        self.assertNotIn("MEDIA_JOBS_REQUIRE_LEASE_TOKEN=true", compose_text.replace("${", "").replace(":-false}", ""))
        ship_text = (ROOT / "ci/ship.sh").read_text()
        self.assertNotIn("MEDIA_JOBS_REQUIRE_LEASE_TOKEN=true", ship_text)


if __name__ == "__main__":
    unittest.main()
