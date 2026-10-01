import asyncio
import json
import sys

from .orchestrator import SanadOrchestrator
from .web_retrieval import WebDiscoveryPipeline


async def _main():
    if len(sys.argv) < 2:
        print('Usage: python -m sanad_core.main "your question"')
        raise SystemExit(2)

    text = " ".join(sys.argv[1:])
    result = await SanadOrchestrator(
        web_retrieval=WebDiscoveryPipeline()
    ).search(text)
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
