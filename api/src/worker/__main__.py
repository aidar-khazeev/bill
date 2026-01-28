import logging
import asyncio
from . import run_loop


if __name__ == '__main__':
    logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(levelname)s: %(message)s')
    asyncio.run(run_loop())