# Krill Pi Sidecar

This sidecar embeds Pi for Krill's agent runtime. Krill starts this process per
chat execution, sends a JSON request over stdin, receives JSONL progress events
on stdout, and services Krill-specific MCP tool callbacks over the same pipe.

Install dependencies from this directory with `npm install` when running from a
source checkout. Docker installs the package during image build.
