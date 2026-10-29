# Wiki BLAZE

**Browsing Links A-to-Z Exploration.** Learners start on one Wikipedia article and try to reach a
goal article by clicking links, using as few links as they can. It runs fully offline, using a
Wikipedia `.zim` file already on the device (for example the one Internet-in-a-Box uses for
Kiwix).

## Setting it up (administrators)

1. **Install the game.** On the games page, open **Setup**, choose `org.togetherings.wiki-blaze-<version>.zip`
   (attached to each [release](https://github.com/togetherings/kolibri-games/releases)) and click
   **Install**.
2. **Choose the Wikipedia file.** Still on Setup, under *Wikipedia file for Wiki BLAZE*, pick the
   `.zim` file. Files in `/library/zims/content` (where IIAB keeps them) are listed; choose
   *Another file* to type any other path. Use an English Wikipedia file. The default article list
   (below) works best with a file that has the Wikipedia for Schools articles, such as a full
   English Wikipedia or a "Wikipedia for Schools" ZIM.
3. **libzim** reads the file. `install.sh` installs it. `kolibri manage kolibri_games_check` says
   whether it's there.

## Playing

- **Free play:** a random start and goal each time, 3 to 6 links apart. There's no free-play
  scoreboard, because every round is different. Coaches can set a fixed start and goal for free
  play under *Settings*.
- **Challenges:** a coach sets one up for a class (see below). Everyone in the class gets the
  same start and goal, and the challenge has its own scoreboard.

The rules:

- Only links in the article can be followed. There's no search box or address bar.
- The learner's **chain** (the articles from the start to where they are) is shown at the top.
  Clicking any earlier article goes back to it **for free**: the chain is cut back to there.
- Following a link to an article already in the chain also counts as going back to it, so going
  round in circles never makes the chain longer.
- Links to the goal are highlighted when they appear.
- The **score** is the number of links in the chain when the goal is reached. If two learners tie,
  the faster one ranks higher. Exploring dead ends only costs time.

The server checks every link and keeps the chain, so results can't be faked, even with the
browser's developer tools.

## Challenges (coaches)

On the games page, click **Challenges** on the Wiki BLAZE card, then **New challenge**:

- **Name, class, opening and closing time**, which attempt counts and a time limit, as for any game.
- **Articles learners can visit:** the game's own list (Wikipedia for Schools, about 10,500
  articles curated by SolarSpell), every article in the Wikipedia file, or one of your own lists.
- **Start and goal:** start typing to see matching titles. Leave both blank and a random pair is
  picked once for the whole challenge.

When you save, Kolibri Games checks that both articles exist and are in the chosen list. Then it
works out the **shortest route** in the background and shows it to you on the Challenges page
(for example "5 links: Cat → Mammal → Whale → Ocean → Earth → Moon"). Learners don't see it while
the challenge is open.

**After the challenge closes**, its scoreboard shows everyone's routes and the shortest route.

**Results** show each learner's counted route, and under *History* every step: each link
followed and each time they went back, with times.

### Article lists

On the games page, click **Article lists**. A list has a name and article titles, one per line,
written as on Wikipedia ("Solar System" or "Solar_System"). You can paste titles or load a text
file. After saving, the page shows how many titles were found in the Wikipedia file and which
weren't (often a spelling difference, or an article the file doesn't have). Lists belong to your
facility and can be chosen for any challenge.

Learners can only follow links to articles in the chosen list; other links show as plain text.
Small lists make shorter, more focused races, but if a list is too small some articles may have no
usable links.

## How it stays light on a Raspberry Pi

- Articles are read from the ZIM file only when someone opens them. The last 48 cleaned articles
  are kept in memory, since a class often starts on the same article.
- An article list is matched against the Wikipedia file once (about a second for 10,000 titles)
  and then remembered.
- The shortest-route search runs in the background, one at a time, and pauses every few pages so
  the server keeps answering learners. It stops after 20,000 pages or 90 seconds; if the articles
  are further apart than that, the challenge shows "too far apart to work out" and everything
  else still works.
- Random pairs are made with a short random walk, which reads only a handful of articles.

## For game makers: the `wikipedia-race` service

Wiki BLAZE is an ordinary Free-play Game whose manifest asks for a server feature:

```json
"service": "wikipedia-race",
"data": [{"name": "wikipedia"}],
"wikipedia": {"default_list": "lists/wikipedia-for-schools.txt", "default_list_name": "Wikipedia for Schools"},
"settings": [
  {"key": "list", "type": "article_list", "label": "Articles learners can visit", "default": "default"},
  {"key": "start", "type": "article", "label": "Start article", "default": ""},
  {"key": "goal", "type": "article", "label": "Goal article", "default": ""}
]
```

With it, `KG.start()` returns the first page in `start.public` (`page`, `chain`, `steps`, `done`,
`start`, `goal`), and moves go through the server:

```js
await KG.move("go", { to: "Mammal" });  // follow a link (its data-to value)
await KG.move("back", { step: 1 });     // go back to article 1 of the chain (0 is the start)
// each reply: {page: {path, title, html}, chain: [{path, title}], steps, done}
await KG.finish({});                    // only after done; the server works out the score
```

The `html` has scripts, styles and forms removed. Links to allowed articles are
`<a data-to="path">`; other links are plain text. Pictures point at `__wiki__/...`, which the
game's own address serves from the Wikipedia file.
