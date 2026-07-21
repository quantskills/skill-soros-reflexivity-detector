# skill-soros-reflexivity-detector (#48)

> Soros Reflexivity Detector · BUILD-type skill · Community Project
> **Reflexivity = the self-reinforcing loop where rising begets rising and falling begets falling.**
> This tool quantifies the *strength and stage* of "price making its own trend."

## What it answers

Three questions that matter for trading:

1. Is this move **self-reinforcing** (can you ride it)?
2. Which **turn of the loop** is it on (position discipline)?
3. Is **fuel** (fresh money) still flowing, is the **tank leaking** (pledge / lockup-release / block trades)?

**Explicitly does NOT**: predict tops/bottoms, judge "value," or assume market efficiency.

## Dual-loop model

| Loop | Circuit | Horizon | Arena |
|---|---|---|---|
| Fast (sentiment-capital) | up → trending → more buyers → up | days–weeks | theme/hot-money stocks |
| Slow (fundamental-capital) | up → placement/buyback → earnings upgrade → up | quarters–years | trending blue chips |
| Dual resonance | both closed | — | strongest reflexivity |

Eight stages: S0 neutral → S1 early → S2 crowd-chasing (with test) → S3 euphoria/twilight → S4 rupture → S5 negative reflexivity.

## Quick start

```bash
pip install --upgrade panda_data pyarrow
export PANDA_USERNAME=<phone>; export PANDA_PASSWORD=<pwd>   # or ~/.pandadata/pandadata.env
python 开发产物/scripts/build.py --mode watchlist --symbols 300750.SZ 688256.SH --date 20260710 --save
python 开发产物/scripts/test.py     # fully offline, green without panda_data
```

## Data & disclaimer

Data source: PandaData (credentials via env vars or `~/.pandadata/pandadata.env`, **never hardcoded**).
HK/Shanghai-Shenzhen Connect per-stock holdings are largely undisclosed after 2024/08 → that component defaults to zero weight.

**Community Project, not reviewed/certified/endorsed by QuantSkills. Research and educational example only — not investment advice, no return guarantee, no top/bottom prediction.**

License: GPL-3.0-only
