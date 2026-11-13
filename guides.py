"""Public how-to guides (1.116.0): xctimer.com/guides.

Plain, useful answers to the questions coaches and race directors actually type into a search
box ("how to score a cross country meet", "how to organize a 5k"), each with a short, honest
note on how XCTimer does that job. They exist to be found: the marketing page describes the
product, these pages answer the question.

Facts about XCTimer in here must stay true to the app: cross country team scoring is
xc.team_scores (drop teams under five, keep each team's first seven, re-rank, top five score,
ties on the 6th then 7th runner; an 8th runner and beyond hold no team place -- if that engine
rule changes, change the guide's "Let the meet score itself" box with it); the finish-line method is the same one the assistants teach
(insights._PLATFORM_HELP, BIB BOARD).
"""
from flask import Blueprint, abort, make_response

from . import billing, road
from .ui import seo_head

bp = Blueprint("guides", __name__)

CSS = """
:root{--ink:#0c1929;--ink2:#13283f;--orange:#f0641e;--orange-d:#d4530f;--gray:#6b7684;
      --body:#212b36;--bg:#f6f7f9;--line:#e6e9ee;--green:#2e9e5b}
*{box-sizing:border-box}
body{margin:0;font:17px/1.7 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:var(--body);background:#fff}
a{color:var(--orange-d)}
nav{background:var(--ink);border-bottom:4px solid var(--orange)}
nav .in{max-width:760px;margin:0 auto;padding:0 1.2rem;height:58px;display:flex;align-items:center;
        justify-content:space-between}
.wordmark{font-weight:800;font-size:1.2rem;letter-spacing:-.02em;text-decoration:none;color:#fff}
.wordmark b{color:var(--orange)} .wordmark i{font-style:normal;color:#7f93a8;font-size:.85em}
nav .links a{color:#c9d5e2;font-weight:700;text-decoration:none;margin-left:1.1rem;font-size:.95rem}
nav .links a:hover{color:#fff}
main{max-width:760px;margin:0 auto;padding:2.2rem 1.2rem 3rem}
.crumb{font-size:.9rem;color:var(--gray);margin:0 0 .6rem} .crumb a{color:var(--gray)}
h1{font-size:clamp(1.8rem,5vw,2.5rem);line-height:1.15;color:var(--ink);letter-spacing:-.015em;margin:0 0 .6rem}
h2{font-size:1.4rem;color:var(--ink);margin:2.1rem 0 .5rem;letter-spacing:-.01em}
h3{font-size:1.08rem;color:var(--ink);margin:1.3rem 0 .3rem}
.lede{font-size:1.15rem;color:#4a5766;margin:0 0 1.2rem}
ol,ul{padding-left:1.3rem} li{margin:.35rem 0}
table{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.95rem}
th,td{border-bottom:1px solid var(--line);padding:.45rem .5rem;text-align:left}
th{color:var(--gray);font-size:.78rem;letter-spacing:.06em;text-transform:uppercase}
td.n{text-align:right;font-variant-numeric:tabular-nums} .tw{overflow-x:auto}
.box{background:var(--bg);border:1px solid var(--line);border-radius:14px;padding:1.1rem 1.3rem;margin:1.4rem 0}
.box.x{border:2px solid var(--orange);background:#fff8f3}
.box h2,.box h3{margin-top:0}
.btn{display:inline-block;background:var(--orange);color:#fff;font-weight:700;padding:.65rem 1.3rem;
     border-radius:10px;text-decoration:none;margin:.3rem .5rem .3rem 0}
.btn.g{background:transparent;color:var(--ink);border:1.5px solid #cfd6de}
.cards{display:grid;gap:1rem;margin-top:1.4rem}
.cards a{display:block;border:1px solid var(--line);border-radius:14px;padding:1.1rem 1.3rem;text-decoration:none;color:var(--body)}
.cards a:hover{border-color:var(--orange)} .cards b{display:block;color:var(--ink);font-size:1.12rem}
.cards span{color:#4a5766;font-size:.96rem}
footer{border-top:1px solid var(--line);color:var(--gray);font-size:.88rem;text-align:center;padding:1.4rem 1rem}
footer a{color:var(--gray)}
"""


def _fee():
    return billing.fee_str()


# ------------------------------------------------------------------ the guides
def _score_xc():
    return f"""
<p class="lede">Cross country is scored by place, not by time. Each team adds up the finishing
places of its first five runners, and the lowest total wins. Here is the whole method, with a
worked example you can check your own results against.</p>

<h2>The five steps</h2>
<ol>
<li><b>Write down the finish order.</b> Every runner gets a place: 1st, 2nd, 3rd and so on. Times
are nice to have, but only the order matters for the team score.</li>
<li><b>Take out runners who do not count for a team.</b> A team needs five finishers to score. Runners
from a team with fewer than five, and runners with no team, are removed, and everyone behind them
moves up a place.</li>
<li><b>Decide what happens after a team's seventh runner.</b> In a varsity race each team enters at
most seven, so this never comes up. In open, junior varsity and many middle school races with big
squads, the usual rule is that a team's eighth runner and beyond are also removed from the team
count. Some leagues let every finisher keep a place instead. Agree on it before the race.</li>
<li><b>Add each team's first five places.</b> That total is the team score.</li>
<li><b>Lowest score wins.</b> The best possible score is 15, which is 1 + 2 + 3 + 4 + 5.</li>
</ol>

<h2>What the sixth and seventh runners do</h2>
<p>A team's sixth and seventh runners do not add to their own team's score. They still hold a
place in the finish order, so they push the other teams' scorers back. Coaches call them
displacers. A strong sixth runner who beats another team's fifth can decide a close meet.</p>

<h2>A worked example</h2>
<p>Sixteen runners finish. Cedar Ridge and Maple Valley each have six. Summit View has only four,
so its runners come out and everyone else moves up.</p>
<div class="tw"><table>
<tr><th>Finish</th><th>Team</th><th>Team place</th><th>Counts as</th></tr>
<tr><td class="n">1</td><td>Cedar Ridge</td><td class="n">1</td><td>Scorer</td></tr>
<tr><td class="n">2</td><td>Maple Valley</td><td class="n">2</td><td>Scorer</td></tr>
<tr><td class="n">3</td><td>Summit View</td><td class="n">–</td><td>Removed (team of four)</td></tr>
<tr><td class="n">4</td><td>Cedar Ridge</td><td class="n">3</td><td>Scorer</td></tr>
<tr><td class="n">5</td><td>Maple Valley</td><td class="n">4</td><td>Scorer</td></tr>
<tr><td class="n">6</td><td>Maple Valley</td><td class="n">5</td><td>Scorer</td></tr>
<tr><td class="n">7</td><td>Summit View</td><td class="n">–</td><td>Removed</td></tr>
<tr><td class="n">8</td><td>Cedar Ridge</td><td class="n">6</td><td>Scorer</td></tr>
<tr><td class="n">9</td><td>Cedar Ridge</td><td class="n">7</td><td>Scorer</td></tr>
<tr><td class="n">10</td><td>Maple Valley</td><td class="n">8</td><td>Scorer</td></tr>
<tr><td class="n">11</td><td>Summit View</td><td class="n">–</td><td>Removed</td></tr>
<tr><td class="n">12</td><td>Cedar Ridge</td><td class="n">9</td><td>Scorer</td></tr>
<tr><td class="n">13</td><td>Maple Valley</td><td class="n">10</td><td>Scorer</td></tr>
<tr><td class="n">14</td><td>Summit View</td><td class="n">–</td><td>Removed</td></tr>
<tr><td class="n">15</td><td>Cedar Ridge</td><td class="n">11</td><td>Sixth runner</td></tr>
<tr><td class="n">16</td><td>Maple Valley</td><td class="n">12</td><td>Sixth runner</td></tr>
</table></div>
<p><b>Cedar Ridge:</b> 1 + 3 + 6 + 7 + 9 = <b>26</b>. <b>Maple Valley:</b> 2 + 4 + 5 + 8 + 10 =
<b>29</b>. Cedar Ridge wins, 26 to 29. Summit View has no team score, though its runners keep
their individual places and times.</p>

<h2>Breaking a tie</h2>
<p>Under high school rules in the United States, a tied team score goes to the team whose sixth
runner finished ahead. If only one of the tied teams has a sixth runner, that team wins. Middle
school and junior high leagues usually follow the same rule, but some break ties another way, so
check your league's handbook before the season.</p>

<h2>Mistakes that change the result</h2>
<ul>
<li><b>Scoring before removing incomplete teams.</b> Leave the four-runner team in and every score
behind it is wrong.</li>
<li><b>Not agreeing on big squads.</b> Whether an eighth runner holds a team place changes the
score, so settle it with the other coaches first.</li>
<li><b>Mixing races.</b> Boys and girls, and each grade or division, are scored separately.</li>
<li><b>Adding times.</b> Team time is a different statistic. The team score is places.</li>
<li><b>A wrong finish order.</b> One swapped pair of runners can flip a close meet, which is why a
paper record of the order matters. See <a href="/guides/how-to-time-a-cross-country-meet">how to
time a cross country meet</a>.</li>
</ul>

<div class="box x">
<h2>Let the meet score itself</h2>
<p>XCTimer scores the meet as the race finishes. It drops teams with fewer than five, takes out
each team's eighth runner and beyond, moves everyone up, adds each school's first five, and breaks ties on the sixth runner, then the seventh.
Only a team's first seven finishers hold a team place, so a big squad's eighth runner and beyond
cannot push another team's scorers back. Scores are
kept separately for each race, and by grade and gender, and they update on the live results page
while runners are still coming in.</p>
<p>Setting up a meet is free. It is {_fee()} when the meet goes live.</p>
<a class="btn" href="/start">Set up your school</a><a class="btn g" href="/pricing">See pricing</a>
</div>
"""


def _time_xc():
    return f"""
<p class="lede">You can time a cross country meet accurately with a phone, a few helpers and a
poster board. No chips, no mats, no timing company. This is the method we use at junior high
meets, including the paper backup that settles every timing question afterwards.</p>

<h2>What you need</h2>
<ul>
<li><b>Numbered bibs</b> on every runner. Sticker bibs on the front of the shirt work well.</li>
<li><b>A finish chute:</b> two lines of cones or flagging, a few yards wide at the line and narrowing
to single file, long enough to hold a pack of finishers.</li>
<li><b>Three helpers:</b> one to record times at the line, one to keep runners in order in the chute,
one to collect bibs at the end of it.</li>
<li><b>A poster board and a marker</b> for each race.</li>
<li><b>One phone</b> for timing. A second phone is a useful spare.</li>
</ul>

<h2>The method</h2>
<ol>
<li><b>Start the clock with the gun.</b> One person starts the timer as the race starts.</li>
<li><b>Record a time for every runner who crosses.</b> The helper at the line taps once for each
finisher. That captures the time and the place. They do not look at bib numbers at all.</li>
<li><b>Keep the order in the chute.</b> Runners stay in single file, in the order they finished, until
they reach the end. Nobody passes, nobody steps out.</li>
<li><b>Collect the bibs in order.</b> At the end of the chute a helper peels each bib and sticks it on
the poster board, top to bottom, in exactly the order the runners arrive.</li>
<li><b>Match bibs to times.</b> The first bib on the board belongs to the first time, the second to
the second, and so on down the list.</li>
</ol>

<h2>Why the poster board matters</h2>
<p>The board is the paper record of the finish order. If a coach questions a place, if two runners
look swapped, or if the count of times and the count of bibs do not match, you compare the board
to the results and fix it in a minute. Without it you are relying on memory. Use one board per
race and write the race name at the top.</p>

<h2>Common problems and what to do</h2>
<ul>
<li><b>A pack finishes together.</b> Tap for each runner as they cross and sort the order out in the
chute. The chute order is the official order.</li>
<li><b>You missed a tap.</b> Do not stop. Keep tapping, then insert the missing runner at the right
place afterwards using the board.</li>
<li><b>A runner lost their bib.</b> Write the name on the board in their place.</li>
<li><b>More times than bibs, or the reverse.</b> Count both before you publish. The board tells you
where the extra or missing one is.</li>
</ul>

<h2>How many helpers for how many runners</h2>
<p>For a race of up to about 60 runners, three helpers are enough. For bigger fields, add a second
person in the chute and split the bib collecting between two people working side by side on the
same board. Run boys and girls, or each grade, as separate races so a pack never overwhelms the line.</p>

<div class="box x">
<h2>Doing it with XCTimer</h2>
<p>XCTimer is built around this method. A helper taps each finisher on the Phone Timer App, which
opens from a QR code with no login. Bibs print as stickers with a square tag the phone camera can
read. Point the camera at the bibs on your poster board, top to bottom, and each one fills the
next open place. The camera records a bib only once, so there are no duplicate scans, and it
keeps working after the clock is stopped. Results and team scores appear on a live page parents
can follow from the fence.</p>
<p>Setting up a meet is free. It is {_fee()} when the meet goes live.</p>
<a class="btn" href="/start">Set up your school</a>
<a class="btn g" href="/guides/how-to-score-a-cross-country-meet">How scoring works</a>
</div>
"""


def _organize_5k():
    from .road import HOST_FEE_CENTS, _fee_whole
    fee = _fee_whole(HOST_FEE_CENTS)
    return f"""
<p class="lede">A first 5K or fun run is very doable with a small team and about three months of
lead time. This is the order to do things in, what each piece costs, and where first-time race
directors usually get caught out.</p>

<h2>Three months out: the decisions</h2>
<ul>
<li><b>Purpose and size.</b> A school or charity fundraiser, a community event, or a club race. Be
honest about turnout: most first-year local races draw 50 to 200 people.</li>
<li><b>Date.</b> Check the local race calendar, school calendars and holidays for clashes.</li>
<li><b>Course.</b> A park, a school campus or a trail is far simpler than public roads. Measure it
with a GPS watch or a mapping tool and walk it for hazards.</li>
<li><b>Permission.</b> Ask the park, school or city what they require. Road courses often need a
permit and traffic control, and that can take weeks.</li>
<li><b>Insurance.</b> Many venues require event liability cover. Ask what they need in writing.</li>
<li><b>Budget.</b> List every cost before you set the entry fee. See the table below.</li>
</ul>

<h2>Two months out: sign-ups</h2>
<ul>
<li><b>Open registration</b> with a page people can reach from a link or QR code. Collect name, age,
gender and which race they are entering. Include a waiver.</li>
<li><b>Set age groups</b> if you plan awards, for example 10 and under, 11 to 14, 15 to 19, then by
decade.</li>
<li><b>Promote it</b> where your runners already are: school newsletters, local Facebook groups,
running clubs, a banner at the venue.</li>
<li><b>Recruit volunteers.</b> Plan on one for every 15 to 20 runners: registration table, course
marshals at every turn, a water station, the finish line and results.</li>
</ul>

<h2>The last two weeks</h2>
<ul>
<li><b>Order or print bibs</b>, with spares for people who sign up on the day.</li>
<li><b>Mark the course</b> the day before with cones, arrows and flagging. Put a volunteer at every
place a runner could go wrong.</li>
<li><b>Plan the finish line:</b> a clear line, a chute to keep finishers in order, water just past it.</li>
<li><b>Have a first aid plan</b> and know who is calling for help if it is needed.</li>
<li><b>Send a final email</b> with parking, start time and where to pick up bibs.</li>
</ul>

<h2>Timing: your three choices</h2>
<div class="tw"><table>
<tr><th>Option</th><th>Typical cost</th><th>Good for</th></tr>
<tr><td>Stopwatch and a clipboard</td><td>Free</td><td>Very small runs where places matter more than times</td></tr>
<tr><td>A phone timing app you run yourself</td><td>About {fee} or less</td><td>Most fun runs and community 5Ks up to a few hundred runners</td></tr>
<tr><td>A hired chip timing company</td><td>$500 to $1,000 or more</td><td>Large races, road races with split points, certified results</td></tr>
</table></div>
<p>Whatever you choose, keep runners in finish order in a chute and keep a paper record of that
order. It is the only thing that settles an argument about places afterwards.</p>

<h2>A simple budget</h2>
<div class="tw"><table>
<tr><th>Item</th><th>What to expect</th></tr>
<tr><td>Venue or permit</td><td>Free at many schools and parks; public roads cost more</td></tr>
<tr><td>Insurance</td><td>Ask the venue what it requires</td></tr>
<tr><td>Bibs and pins</td><td>Under a dollar a runner, or print your own on label sheets</td></tr>
<tr><td>Timing</td><td>Free to $1,000 or more, as above</td></tr>
<tr><td>Water, cups, snacks</td><td>Often donated by a local sponsor</td></tr>
<tr><td>Shirts and awards</td><td>Optional, and usually the biggest cost if you add them</td></tr>
</table></div>
<p>For a fundraiser, sponsors covering the fixed costs is what makes the entry fees turn into
money raised.</p>

<h2>School fun runs and fundraisers</h2>
<p>A school fun run works the same way with one difference: you are timing children, so keep the
data you collect to a minimum and run each grade as its own short race. If your event counts
laps for pledges instead of timing a distance, you need lap counters, not a race timer.</p>

<div class="box x">
<h2>Running it with XCTimer</h2>
<p>XCTimer gives you the public sign-up page with a QR code, printed bib stickers with your logo,
phone timing, and live results by gender and age group, all from one link you manage yourself.
Build the event free. It is {fee} to open registration, and your first event is
{road.FIRST_EVENT_OFFER}.</p>
<a class="btn" href="/host">Set up a fun run</a><a class="btn g" href="/pricing">See pricing</a>
</div>
"""


def _run_track():
    return f"""
<p class="lede">This is how a junior high or middle school track meet runs in XCTimer, from setup
to final team scores. Every step below is a screen in the app, so you can follow along with your
meet open. Timing is done on phones: no stopwatches, no clipboards, and nobody copying times into
a computer afterwards.</p>

<h2>Before the meet</h2>
<ol>
<li><b>Create the meet.</b> On Meets, choose Track &amp; Field. On the meet's Setup tab, tick the
schools that are coming, choose the points table, and set the event limit (4 by default; relays
do not count toward it) and the number of lanes on your track.</li>
<li><b>Add events.</b> Tick the events, Boys and Girls, and the grades. XCTimer creates one event
for every combination, such as 100m Girls 7th. Drag the event types into the order they will run.</li>
<li><b>Enter athletes.</b> Each coach opens <b>Assign athletes</b> and ticks events beside each
athlete. XCTimer stops anyone going over the event limit. <b>Carry over last meet</b> copies the
entries from your last meet. Visiting teams get one invite link and enter their own athletes.</li>
<li><b>Lock bibs and print.</b> Bibs number from 1 at every meet. Lock them on the Setup tab, then
print each school's stickers and bib list from Assign athletes.</li>
</ol>

<h2>Heats and lanes</h2>
<ul>
<li><b>Seed by season best</b> (Race day tab) uses each athlete's best time in that event from
earlier meets in XCTimer; a relay uses the school's best. The fastest heat runs last, and within a
heat the fastest runners get the middle lanes. Athletes with no earlier time go in after the seeded
ones, in random order.</li>
<li><b>Random draw</b> ignores times. Use it at the first meet of the season.</li>
<li><b>Sprints</b> put one athlete in each lane. <b>Distance races</b> stay in one section until
there are more than twice as many runners as lanes (17 or more on an 8-lane track), then split.</li>
<li><b>Clear draw</b> if entries change on the day, then draw again.</li>
<li><b>Combine races</b> to run two divisions together, such as 7th and 8th grade girls in one
1600m. XCTimer still places and scores each division separately.</li>
<li><b>Heat sheets</b> print as one meet packet or one event at a time. Each sheet has a code in the
top right corner so a phone photo of it is matched to the right event.</li>
</ul>

<h2>Phones on race day</h2>
<p>The Race day tab shows a <b>Phone Timer App</b> QR code. Every helper scans it and lands in the
Track Timer with no login and no app to install. It has three tabs: <b>Time</b> for races,
<b>Scan</b> for photographed sheets, and <b>Pit</b> for field events. A coach who is already signed
in keeps their own login.</p>

<h2>Sprints, hurdles and short relays</h2>
<p>100m, 200m, 400m, hurdles, 4×100m and 4×200m are timed lane by lane.</p>
<ol>
<li><b>The starter</b> stands at the start line, opens the heat under <b>Sprints &amp; relays</b>,
and taps <b>Start</b> at the gun. Or they tap <b>Auto-start: listen for the gun</b> and the phone
starts the clock itself on the bang.</li>
<li><b>Lane timers</b>, one per lane at the finish, open the same heat and pick their lane. The
athlete's name shows beside each lane. Each timer taps once when their runner crosses the line.</li>
<li>Each time appears beside its lane the moment it is tapped and goes straight into the results.</li>
<li>After the heat, everyone taps <b>Next heat</b> together. A false start? The starter taps
<b>Reset race</b> and starts again.</li>
</ol>
<p><b>Why the finish doesn't wait for the gun.</b> All the phones share one race clock, and the start
is stamped by the starter's phone at the start line. The finish-line timers never have to see the
smoke or hear the gun; they only tap when their runner crosses. XCTimer keeps the exact time each
timer tapped and does not round it.</p>

<h2>Distance races and long relays</h2>
<p>800m, 1600m, 3200m, 4×400m, 4×800m and the medleys are timed by tapping each finisher.</p>
<ol>
<li>On the <b>Time</b> tab, pick the event and heat and open the race timer. Start it at the gun, or
use listen for the gun.</li>
<li>One helper taps <b>TAP finisher</b> once for every runner who crosses, in order, without stopping
to read names. A second phone can open the same heat as a backup; both share the clock and the list.</li>
<li>After the race, go down the list and choose who each time belongs to, or type a bib for anyone
not in the list. For a relay, choose the team.</li>
<li>Keep the printed heat sheet at the line and write bib numbers in the order runners finish. That
is your record if a place is questioned.</li>
</ol>

<h2>Field events</h2>
<p>Use whichever way suits each pit crew.</p>
<ul>
<li><b>Pit tab, by bib.</b> Whoever steps up, the crew types the bib (the name appears to confirm it)
and enters the three attempts. Type feet and inches with a space: <b>10 6</b> is 10&prime;6&Prime;.
Type <b>F</b> for a foul. The best legal attempt counts, and the mark files into that athlete's own
grade and gender automatically, so one phone covers every division at that pit.</li>
<li><b>Paper, then scan.</b> The crew writes marks on the printed sheet. On the <b>Scan</b> tab,
photograph it with the code in the corner in view. XCTimer reads the handwriting and shows every row
to check and correct before you post it.</li>
<li><b>Typed in on a laptop</b> on the event's page.</li>
</ul>
<p><b>High jump and pole vault.</b> The Pit tab records the best height cleared. For bar-by-bar
records, the event's page has a make/miss grid: the bar heights come from your meet setup (girls get
the lowest ten bars, boys the top ten), and you enter O for a clear, X for a miss, P for a pass and
XXX for out. XCTimer works out each jumper's best height. Jumpers who clear the same best height share
the place and split the points; XCTimer does not use misses to break the tie.</p>

<h2>Results and team scores</h2>
<p>Each event ranks itself as marks come in, and disqualified athletes are left out. Places earn
points from the table you chose on the Setup tab, and relays use the same table:</p>
<div class="tw"><table>
<tr><th>Points table</th><th>Points by place</th></tr>
<tr><td>Dual meet</td><td>5, 3, 1</td></tr>
<tr><td>Dual or small meet</td><td>5, 3, 2, 1</td></tr>
<tr><td>Invitational, six places</td><td>10, 8, 6, 4, 2, 1</td></tr>
<tr><td>Invitational, eight places</td><td>10, 8, 6, 5, 4, 3, 2, 1</td></tr>
</table></div>
<p><b>Ties split the points.</b> Two athletes who tie for second in a six-place invitational share
the points for second and third: 8 plus 6 is 14, so each gets 7. The next athlete is fourth and gets
4. Boys' and girls' team totals are kept separately.</p>
<p>The Results tab has a live public page with a QR code for the scoreboard or the stands, and an
Excel export when the meet is over.</p>

<h2>Who you need</h2>
<div class="tw"><table>
<tr><th>Job</th><th>How many</th><th>What they do in XCTimer</th></tr>
<tr><td>Starter</td><td class="n">1</td><td>Starts every race from their phone at the start line</td></tr>
<tr><td>Lane timers</td><td class="n">1 per lane</td><td>Each taps their own lane in the sprints</td></tr>
<tr><td>Distance timer</td><td class="n">1, plus a spare</td><td>Taps every finisher, then matches times to names</td></tr>
<tr><td>Finish judge</td><td class="n">1</td><td>Writes the order of finish on the heat sheet</td></tr>
<tr><td>Field crews</td><td class="n">2 per event</td><td>Measure, then enter marks on the Pit tab or the sheet</td></tr>
<tr><td>Clerk</td><td class="n">1</td><td>Lines up the next heat from the heat sheet</td></tr>
</table></div>
<p>You do not need a results person: every time and mark posts itself.</p>

<div class="box x">
<h2>Try it on your next meet</h2>
<p>Setting up a meet is free: events, entries, heats, lanes and printing. It is {_fee()} when the
meet goes live and timing turns on.</p>
<a class="btn" href="/start">Set up your school</a><a class="btn g" href="/pricing">See pricing</a>
</div>
"""


GUIDES = {
    "how-to-score-a-cross-country-meet": {
        "title": "How to Score a Cross Country Meet",
        "h1": "How to score a cross country meet",
        "blurb": "Places, not times: the five steps, displacers, tie-breaks and a worked example.",
        "desc": "How cross country scoring works: add each team's first five places, lowest score wins. "
                "Displacers, incomplete teams, tie-breaks and a worked example.",
        "body": _score_xc,
    },
    "how-to-time-a-cross-country-meet": {
        "title": "How to Time a Cross Country Meet With a Phone",
        "h1": "How to time a cross country meet with a phone",
        "blurb": "A finish chute, three helpers and a poster board. No chips or timing company.",
        "desc": "Time a cross country meet without chip timing: tap each finisher on a phone, keep runners "
                "in chute order, and collect bibs on a poster board as the paper record.",
        "body": _time_xc,
    },
    "how-to-run-a-track-meet": {
        "title": "How to Run a Middle School Track Meet",
        "h1": "How to run a middle school track meet",
        "blurb": "Step by step in XCTimer: entries, heats and lanes, phone timing, field events and team points.",
        "desc": "How to run a junior high or middle school track meet with phones: entries, heats and "
                "lanes, lane timing for sprints, tap timing for distance, field events by bib, and team points.",
        "body": _run_track,
    },
    "how-to-organize-a-5k": {
        "title": "How to Organize a 5K or Fun Run",
        "h1": "How to organize a 5K or fun run",
        "blurb": "A three-month checklist: course, permits, sign-ups, volunteers, timing and budget.",
        "desc": "A first-timer's checklist for organizing a 5K or fun run: course and permits, registration, "
                "volunteers, timing options and what each costs.",
        "body": _organize_5k,
    },
}
PATHS = ("/guides",) + tuple(f"/guides/{slug}" for slug in GUIDES)


def _page(title, path, desc, inner):
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>{title} | XCTimer</title>
{seo_head(path, desc)}
<style>{CSS}</style></head><body>
<nav><div class="in">
  <a class="wordmark" href="/welcome"><b>xc</b>t<b>i</b>mer<i>.com</i></a>
  <span class="links"><a href="/guides">Guides</a><a href="/pricing">Pricing</a><a href="/login">Sign in</a></span>
</div></nav>
<main>{inner}</main>
<footer>© XCTimer · <a href="/welcome">xctimer.com</a> · cross country &amp; track meet timing you run yourself
· <a href="/guides">Guides</a> · <a href="/pricing">Pricing</a></footer>
</body></html>"""


@bp.get("/guides")
def index():
    cards = "".join(f'<a href="/guides/{slug}"><b>{g["h1"]}</b><span>{g["blurb"]}</span></a>'
                    for slug, g in GUIDES.items())
    inner = (f'<h1>Guides for coaches and race directors</h1>'
             f'<p class="lede">Short, practical answers to the questions that come up when you run your own '
             f'cross country meet, track meet or fun run.</p><div class="cards">{cards}</div>')
    return make_response(_page("Guides for Coaches and Race Directors", "/guides",
                               "How-to guides for running your own cross country meet, track meet or fun "
                               "run: scoring, timing with a phone, and organizing a 5K.", inner))


@bp.get("/guides/<slug>")
def guide(slug):
    g = GUIDES.get(slug)
    if not g:
        abort(404)
    more = "".join(f'<li><a href="/guides/{s}">{o["h1"]}</a></li>' for s, o in GUIDES.items() if s != slug)
    inner = (f'<p class="crumb"><a href="/guides">Guides</a> ›</p><h1>{g["h1"]}</h1>{g["body"]()}'
             f'<h2>More guides</h2><ul>{more}</ul>')
    return make_response(_page(g["title"], f"/guides/{slug}", g["desc"], inner))
