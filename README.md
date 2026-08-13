# Today's Top Deals (game-deals)

> Track the **best video game deals** — Epic giveaways, biggest Steam discounts and all-time low price alerts.

A small Python + Streamlit app that tracks video game deals:

- **Free games on the Epic Games Store** (current + upcoming giveaways)
- **Biggest Steam discounts** right now
- **All-time low (ATL) price alerts** for popular games
- **Price history charts** for each tracked game

Prices are fetched from public APIs (no keys needed):
- Steam: `https://store.steampowered.com/api/appdetails`
- Epic: `https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions`

## How it works

- `popular_games.py` - curated list of ~110 popular Steam games with app IDs
- `deal_checker.py` - fetches prices, tracks history in `data/history.json`,
  detects new all-time lows and Epic giveaways
- `app.py` - the Streamlit page ("Today's Top Deals")
- `.github/workflows/daily-deal-check.yml` - runs `deal_checker.py --update`
  once a day and commits the fresh price history, so all-time lows stay
  accurate even when nobody visits the app

## Live demo

The web version is **live** on:

**[https://pythongreatagain.com/game-deals/](https://pythongreatagain.com/game-deals/)**

It's part of **[Make Python Great Again](https://pythongreatagain.com/)** — a growing collection of free Python tools that solve everyday problems.

## Run locally

```bash
pip install -r requirements.txt
python deal_checker.py --update   # build up price history
streamlit run app.py
```

> ATL detection needs history: on the very first run every current price
> becomes the baseline, and new all-time lows appear from then on.

## Deploy on Streamlit Cloud

1. Push this folder to a GitHub repo.
2. Go to <https://share.streamlit.io> -> **Create app**.
3. Pick the repo, branch `main` and `app.py` as the main file.
4. Deploy - the GitHub Actions workflow keeps the history fresh daily.

## Embed on your website

```html
<iframe
  src="https://pythongreatagain.com/game-deals/?embed=true"
  width="100%"
  height="1200"
  frameborder="0"
  allowfullscreen>
</iframe>
```

## Add / remove games

Edit the `POPULAR_GAMES` dict in `popular_games.py` and commit. The next
daily check will pick them up.
