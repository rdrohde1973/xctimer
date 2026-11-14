"""Public how-to guides (1.116.0): xctimer.com/guides.

Every guide is how to do the job in XCTimer, step by step, screen by screen, with the app's own
button labels (Rob, 2026-11-13/14: "the process XCTimer uses ... not the normal way"; anyone
reading already knows the traditional way). No general officiating or race-planning advice.

Facts in here must stay true to the app. Cross country team scoring is xc.team_scores (drop teams
under five, keep each team's first seven, re-rank, top five score, ties on the 6th then 7th runner,
an 8th runner and beyond holds no team place): if that changes, change the XC guide's "Results and
team scores". Keep the guides in step with the assistants too (insights._PLATFORM_HELP, BIB BOARD).
"""
from flask import Blueprint, abort, make_response, redirect

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
def _time_xc():
    return f"""
<p class="lede">This is how a cross country meet runs in XCTimer, from setup to team scores. Every
step below is a screen in the app, so you can follow along with your meet open. One phone times the
finish, a poster board keeps the finish order, and the phone camera puts the names on the times. No
chips, no mats, no timing company.</p>

<h2>Before the meet</h2>
<ol>
<li><b>Create the meet.</b> On Meets, choose Cross Country, set the date and tick the schools that
are coming. XCTimer makes a Boys heat and a Girls heat. On the Setup tab, rename them or add one heat
per race you will run, such as 7th Girls. Team scoring is on unless you untick it.</li>
<li><b>Bibs are numbered for you.</b> Every cross country runner on each attending school's roster
gets a bib for this meet, numbered from 1. Visiting teams get one invite link and add their own
runners.</li>
<li><b>Lock bibs and print.</b> On the Setup tab, tap <b>Lock bibs &amp; enable printing</b> so the
numbers cannot shift. Then, on the Race day tab, print the sticker sheets and the bib lists. Each
sticker has the runner's name, the school logo and a square tag the phone camera reads. Avery 5523 weatherproof labels hold up to rain and
sweat; any Avery 5163-size sheet works.</li>
<li><b>Map the course</b> if you like. On the Course tab, click points along the route on the
satellite map. Parents get a fly-over of the course from the results page.</li>
</ol>

<h2>What to bring</h2>
<ul>
<li>The <b>bib stickers</b>, worn on the front of the shirt.</li>
<li>A <b>finish chute</b>: two lines of cones or flagging, a few yards wide at the line and narrowing
to single file, long enough to hold a pack.</li>
<li>A <b>poster board and a marker</b> for each race.</li>
<li><b>Two or three phones</b>, charged: see How many phones below.</li>
</ul>

<h2>Phones on race day</h2>
<p>The Race day tab shows a <b>Phone Timer App</b> QR code. Every helper scans it and lands in the
timer with no login and no app to install. They pick the heat they are working, and every phone on
that heat shows the same clock and the same finish list.</p>

<h3>How many phones</h3>
<ul>
<li><b>Three phones</b> when the start is out of sight of the finish: one for the starter, one for the
finish timer, and one to scan the bib board.</li>
<li><b>Two phones</b> when the start and finish are close together: the starter starts the heat
and carries the same phone to the finish line to tap finishers. A second phone scans the bib
board.</li>
</ul>
<p>Either way, keep the scanning phone separate from the tapping phone, so nobody has to stop tapping
to scan. A spare phone with the timer open is cheap insurance.</p>

<h2>The start</h2>
<p>The starter stands at the start line with the heat open and taps <b>START</b> at the gun. Or they
tap <b>Auto-start: listen for the gun</b> and the phone starts the clock itself on the bang.</p>
<p><b>Why the finish doesn't wait for the gun.</b> The start is stamped on the starter's phone at the
line, and every other phone shares that clock. The finish timer may be half a mile away and never has
to see the smoke or hear the gun.</p>

<h2>At the finish line</h2>
<ol>
<li><b>Tap every runner.</b> The finish timer taps <b>FINISHER</b> once as each runner crosses. That
records the time and the place. They do not look at bibs or names. <b>UNDO</b> removes an extra tap.</li>
<li><b>Keep the chute in order.</b> Runners stay single file, in the order they crossed. Nobody passes
and nobody steps out.</li>
<li><b>Build the bib board.</b> At the end of the chute a helper peels each runner's bib sticker and
sticks it on the poster board, top to bottom, in exactly the order the runners arrive. Write the heat
name at the top.</li>
<li>Tap <b>STOP</b> after the last runner. The clock stops; nothing else is lost.</li>
</ol>
<p>For a small race you can skip the taps: the timer shows every runner in the heat, and you tap a
name as that runner crosses. There is a search box for long lists.</p>

<h2>Putting the names on the times</h2>
<ol>
<li>Open the heat in the Phone Timer App and tap the <b>📷</b> at the top.</li>
<li>Point the camera at the bib board and go down it, top to bottom. Each bib it reads fills the next
open place, so the first bib on the board gets the first time.</li>
<li>The camera records a bib only once per race. If it sees one it already has, it ignores it, so you
can sweep back over the board without creating duplicates.</li>
<li>If a sticker is torn or folded and will not read, type the bib number instead.</li>
</ol>
<p>This works after the clock is stopped, so you can scan the board after the last runner is in. Order
matters: scan out of order and names land on the wrong times. A flat bib on a board reads far more
easily than one on the shirt of a tired runner, but you can scan in the chute if you have to.</p>

<h2>Fixing problems</h2>
<p>The race console (<b>⏱ Time</b> on the Race day tab, best on a laptop) lists every place with its
time. The bib board is your check: the board and the console should show the same bibs in the same
order.</p>
<ul>
<li><b>A runner is missing.</b> Click <b>＋↑</b> at the place they belong. The runners below slide down one
place, the times stay where they were tapped, and you type the missing bib into the blank row. If
there is no open place below, the last runner gets an estimated time one second behind the runner
ahead, and XCTimer warns you to check it.</li>
<li><b>Two runners are swapped.</b> Drag them into the right order. The times stay put; the runners
move.</li>
<li><b>A bib number nobody at the meet has.</b> XCTimer records it as "Bib 57" and warns you, so
you can check the board for a misread number.</li>
<li><b>A bib scanned twice.</b> XCTimer says the runner is already in at their place and does not add
them again.</li>
<li><b>A runner with no bib.</b> Use the Walk-ups card on the Race day tab to give them a spare sticker
number, then scan or type it.</li>
<li><b>A disqualification.</b> Mark the runner DQ. They stay listed but lose their place.</li>
</ul>
<p>When the heat is right, tap <b>Lock results</b> so nobody changes it by accident.</p>

<h2 id="results">Results and team scores</h2>
<p>Results build themselves as names go on the times. The Results tab has a live public page with a QR
code for the stands, and an Excel export. Team scores update on that page while runners are still
coming in.</p>
<p>How XCTimer scores each heat:</p>
<ul>
<li>A school needs five finishers for a team score. A school with fewer keeps its individual places
and times, but its runners are taken out of the team places.</li>
<li>Each school's first five finishers score. Lowest total wins.</li>
<li>A school's sixth and seventh runners hold team places, so they can push other teams' scorers back.
An eighth runner and beyond holds no team place.</li>
<li>A tie goes to the team whose sixth runner finished first, then the seventh.</li>
<li>Each heat is scored on its own, and the Results tab also shows team scores by grade and
gender.</li>
<li>Don't want team scores? Untick <b>Team scoring</b> on the Setup tab. Time trials never have
them.</li>
</ul>

<h2>Practice time trials</h2>
<p>A coach can run a time trial for their own team. It has one heat called Time Trial, times exactly
like a meet, and is free. When you time by tapping names, the list puts your fastest runners first,
from their best earlier time trial.</p>

<h2>Who you need</h2>
<div class="tw"><table>
<tr><th>Job</th><th>How many</th><th>What they do in XCTimer</th></tr>
<tr><td>Starter</td><td class="n">1</td><td>Starts each heat from their phone at the start line, and can then tap the finish too</td></tr>
<tr><td>Finish timer</td><td class="n">1</td><td>Taps FINISHER for every runner, then STOP</td></tr>
<tr><td>Chute keeper</td><td class="n">1 or 2</td><td>Keeps runners single file in finish order</td></tr>
<tr><td>Bib collector</td><td class="n">1 per board</td><td>Peels bibs onto the poster board in order</td></tr>
<tr><td>Scanner</td><td class="n">1</td><td>Scans the bib board with their own phone's camera</td></tr>
</table></div>
<p>For fields of more than about 60, add a
second chute keeper and a second bib collector working side by side on the same board, and run boys
and girls, or each grade, as separate heats.</p>

<div class="box x">
<h2>Try it on your next meet</h2>
<p>Setting up a meet is free: schools, heats, bibs and printing. It is {_fee()} when the meet goes live
and timing turns on.</p>
<a class="btn" href="/start">Set up your school</a><a class="btn g" href="/pricing">See pricing</a>
</div>
"""


def _organize_5k():
    from .road import HOST_FEE_CENTS, _fee_whole
    fee = _fee_whole(HOST_FEE_CENTS)
    return f"""
<p class="lede">This is how a 5K or fun run works in XCTimer, from building the event to posting
results. Every step below is a screen in the app, so you can follow along with your event open.
Runners sign up from a link, bibs print on stickers, phones time the finish, and results post
themselves. No chips, no mats, no timing company.</p>

<h2>Build the event</h2>
<ol>
<li><b>Start at <a href="/host">xctimer.com/host</a>.</b> Enter the event name, the date and your
email. XCTimer emails you a private link that opens your event; there is no password. Lost it? Enter
the same email on that page and the link is sent again.</li>
<li><b>Add your races</b> on the Setup tab. XCTimer starts you with a 5K; add a 10K, a 1 mile or a
Kids Fun Run beside it. Each race has its own start, its own clock and its own results.</li>
<li><b>Set age groups</b> on each race, for example <b>10 &amp; Under, 11-14, 15-19, 20-29, 30+</b>.
Copy and paste the same line into the next race to reuse it.</li>
<li><b>Upload your logo.</b> It goes on the sign-up page and on every bib.</li>
</ol>
<p>Building is free. It is {fee} to go live and open registration, paid by card, and your first event
is {road.FIRST_EVENT_OFFER}.</p>

<h2>Open registration</h2>
<ol>
<li>In <b>Event page &amp; registration</b> on the Setup tab, add a welcome message (start time,
parking, packet pickup) and tick <b>Registration open</b>.</li>
<li>Set an <b>entry fee</b> if you charge one. Add your Venmo username and runners are sent to Venmo to
pay right after they sign up. Without Venmo, the page shows the fee as owed and you collect it at
packet pickup.</li>
<li><b>Charity run or school fundraiser?</b> Put the charity's, PTA's or booster club's Venmo
username here and entry fees go straight to that account. XCTimer never touches the money.</li>
<li>Share the <b>public registration link</b> or its QR code: on flyers, in the school newsletter, in
local Facebook groups.</li>
</ol>
<p>Runners need no account. They enter name, age on race day, sex, city and club, pick their race, and
can add family members on the same form. Each one gets a bib number on the spot, and you get an email
for every sign-up. XCTimer collects no email addresses or phone numbers from runners, which keeps a
school fun run simple.</p>

<h2>The Participants tab</h2>
<ul>
<li>Everyone who registered, with their bib, race and age.</li>
<li><b>Add a runner by hand</b>, or <b>import a CSV</b> from another sign-up site. Leave the bib blank
and XCTimer numbers it.</li>
<li><b>Move a runner</b> to a different race from the drop-down beside their name.</li>
<li><b>Print bibs</b>: each sticker has your logo, the bib number, the runner's name and a square tag
the phone camera reads. Add a few blank spares for race-day sign-ups. Avery 5523 weatherproof labels
hold up to rain and sweat; any Avery 5163-size sheet works.</li>
<li><b>Print whenever you like.</b> Spare numbers are held for race-day sign-ups, so anyone who
registers online after you print gets a new number, never one of your spares. Print again later and
XCTimer reuses the spares nobody has taken.</li>
</ul>

<h2>What XCTimer leaves to you</h2>
<p>XCTimer handles sign-ups, bibs, timing and results. These are still yours:</p>
<ul>
<li><b>Permission and insurance.</b> Ask the park, school or city what they require, in writing.</li>
<li><b>A waiver,</b> if your venue wants one. XCTimer's sign-up does not collect one, so have runners
sign at packet pickup.</li>
<li><b>The course.</b> Measure it, mark every turn with cones and arrows, and put a marshal anywhere a
runner could go wrong.</li>
<li><b>Water and first aid,</b> and who calls for help if it is needed.</li>
</ul>

<h2>Race day: the finish chute</h2>
<p>Set out two lines of cones or flagging, a few yards wide at the line and narrowing to single file,
with a <b>poster board and a marker</b> for each race at the end of it.</p>

<h2>Phones on race day</h2>
<p>The Race day tab shows a <b>Phone Timer App</b> QR code. Every helper scans it and lands in the
timer with no login and no app to install. They pick the race they are working, and every phone on
that race shows the same clock and the same finish list.</p>

<h3>How many phones</h3>
<ul>
<li><b>Three phones</b> when the start is out of sight of the finish: one for the starter, one for the
finish timer, and one to scan the bib board.</li>
<li><b>Two phones</b> when the start and finish are close together: the starter starts the race
and carries the same phone to the finish line to tap finishers. A second phone scans the bib
board.</li>
</ul>
<p>Either way, keep the scanning phone separate from the tapping phone, so nobody has to stop tapping
to scan. A spare phone with the timer open is cheap insurance.</p>

<h2>The start</h2>
<p>The starter stands at the start line with the race open and taps <b>START</b> as the race goes. Or
they tap <b>Auto-start: listen for the gun</b> and the phone starts the clock itself on the horn or
the gun.</p>
<p><b>Why the finish doesn't wait for the gun.</b> The start is stamped on the starter's phone at the
line, and every other phone shares that clock. The finish timer can be out of sight of the start and
never has to see or hear it.</p>

<h2>At the finish line</h2>
<ol>
<li><b>Tap every runner.</b> The finish timer taps <b>FINISHER</b> once as each runner crosses. That
records the time and the place. They do not look at bibs. <b>UNDO</b> removes an extra tap.</li>
<li><b>Keep the chute in order.</b> Runners stay single file in the order they crossed.</li>
<li><b>Build the bib board.</b> At the end of the chute a helper peels each runner's bib sticker and
sticks it on the poster board, top to bottom, in exactly the order they arrive. Write the race name at
the top.</li>
<li>Tap <b>STOP</b> after the last runner.</li>
</ol>

<h2>Putting the names on the times</h2>
<ol>
<li>Open the race in the Phone Timer App and tap the <b>📷</b> at the top.</li>
<li>Point the camera at the bib board and go down it, top to bottom. Each bib it reads fills the next
open place, so the first bib on the board gets the first time.</li>
<li>The camera records a bib only once per race, so you can sweep back over the board without creating
duplicates. If a sticker will not read, type the number.</li>
</ol>
<p>This works after the clock is stopped. Order matters: scan out of order and names land on the wrong
times. If you scan a bib that is registered for a different race, XCTimer warns you.</p>

<h2>Two races at once</h2>
<p>If a 10K and a 5K share one finish line, start each race from its own heat in the Phone Timer App.
Then use <b>Scan all races, one camera</b> on the Race day tab: one phone or iPad at the finish reads
every bib as the runner crosses, puts them in the race they registered for and times them from that
race's own start. A 10K that started at 7:45 and a 5K at 8:00 both come out right.</p>

<h2>Race-day sign-ups</h2>
<p>Hand the runner one of your blank spare stickers, then add them on the Participants tab with that
bib number and their race. They are timed like everyone else.</p>

<h2>Fixing problems</h2>
<p>The race console (<b>⏱ Time</b> on the Race day tab, best on a laptop) lists every place with its
time. The bib board is your check: the board and the console should show the same bibs in the same
order.</p>
<ul>
<li><b>A runner is missing.</b> Click <b>＋↑</b> at the place they belong. The runners below slide
down one place, the times stay where they were tapped, and you type the missing bib into the blank
row.</li>
<li><b>Two runners are swapped.</b> Drag them into the right order. The times stay put; the runners
move.</li>
<li><b>A bib nobody registered.</b> XCTimer records it as "Bib 57" and warns you, so you can check
the board for a misread number or add a race-day runner.</li>
</ul>
<p>When a race is right, tap <b>Lock results</b> so nobody changes it by accident.</p>

<h2>Results</h2>
<p>Results build themselves as names go on the times, by sex and age group in each race. The Results
tab has a live public page with a QR code for the crowd and an Excel export. Your event and its
runner list are removed 30 days after the event date, so download the results first.</p>

<h2>School fun runs and charity runs</h2>
<p>Set the entry fee and the school's or charity's Venmo on the Setup tab, and every sign-up is sent
to pay it right away. Run each grade as its own short race so a pack of kids never swamps the finish line. If your event
counts laps for pledges instead of timing a distance, you need lap counters, not a race timer.</p>

<h2>Who you need</h2>
<div class="tw"><table>
<tr><th>Job</th><th>How many</th><th>What they do in XCTimer</th></tr>
<tr><td>Registration table</td><td class="n">1 or 2</td><td>Hands out bibs, adds race-day sign-ups</td></tr>
<tr><td>Starter</td><td class="n">1</td><td>Starts each race from their phone at the start line, and can then tap the finish too</td></tr>
<tr><td>Finish timer</td><td class="n">1</td><td>Taps FINISHER for every runner, then STOP</td></tr>
<tr><td>Chute keeper</td><td class="n">1 or 2</td><td>Keeps runners single file in finish order</td></tr>
<tr><td>Bib collector</td><td class="n">1 per board</td><td>Peels bibs onto the poster board in order</td></tr>
<tr><td>Scanner</td><td class="n">1</td><td>Scans the bib board with their own phone's camera</td></tr>
<tr><td>Course marshals</td><td class="n">1 per turn</td><td>Point runners the right way</td></tr>
</table></div>

<div class="box x">
<h2>Build your event</h2>
<p>Building is free: races, age groups, logo and sign-up page. It is {fee} to go live and open
registration, and your first event is {road.FIRST_EVENT_OFFER}.</p>
<a class="btn" href="/host">Set up a fun run</a><a class="btn g" href="/pricing">See pricing</a>
</div>
"""


def _run_track():
    return f"""
<p class="lede">This is how a school track meet runs in XCTimer, from setup
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
    "how-to-time-a-cross-country-meet": {
        "title": "How to Time a Cross Country Meet with XCTimer",
        "h1": "How to time a cross country meet with XCTimer",
        "blurb": "Bibs, the phone start, tapping finishers, the bib board, camera scanning and team scores.",
        "desc": "How to time a cross country meet with phones in XCTimer: printed bib stickers, a phone "
                "start, tapping each finisher, a poster-board bib record, camera scanning and team scores.",
        "body": _time_xc,
    },
    "how-to-run-a-track-meet": {
        "title": "How to Run a School Track Meet with XCTimer",
        "h1": "How to run a school track meet with XCTimer",
        "blurb": "Entries, heats and lanes, phone timing, field events and team points.",
        "desc": "How to run a school track meet with phones in XCTimer: entries, heats and "
                "lanes, lane timing for sprints, tap timing for distance, field events by bib, and team points.",
        "body": _run_track,
    },
    "how-to-organize-a-5k": {
        "title": "How to Run a 5K or Fun Run with XCTimer",
        "h1": "How to run a 5K or fun run with XCTimer",
        "blurb": "Sign-up page, bib stickers, phone timing, the bib board and results.",
        "desc": "How to run a 5K or fun run in XCTimer: an online sign-up page with a QR code, printed bib "
                "stickers, phone timing at the finish, camera scanning for names and live results by age group.",
        "body": _organize_5k,
    },
}
PATHS = ("/guides",) + tuple(f"/guides/{slug}" for slug in GUIDES)

# Guides that were taken down, and where their address now goes (a permanent redirect, so a
# search result or an old link still lands somewhere useful). Rob, 2026-11-14: every guide is
# how to do it in XCTimer; the general scoring explainer went, and XCTimer's own scoring rules
# live in the cross country guide's "Results and team scores".
RETIRED = {"how-to-score-a-cross-country-meet": "/guides/how-to-time-a-cross-country-meet#results"}


def _page(title, path, desc, inner):
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>{title if "XCTimer" in title else title + " | XCTimer"}</title>
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
             f'<p class="lede">Step by step: how to run your own cross country meet, track meet or fun run '
             f'in XCTimer, screen by screen.</p><div class="cards">{cards}</div>')
    return make_response(_page("Guides for Coaches and Race Directors", "/guides",
                               "Step-by-step guides to running a cross country meet, track meet or fun run "
                               "in XCTimer: setup, phone timing, results and team scores.", inner))


@bp.get("/guides/<slug>")
def guide(slug):
    if slug in RETIRED:
        return redirect(RETIRED[slug], code=301)
    g = GUIDES.get(slug)
    if not g:
        abort(404)
    more = "".join(f'<li><a href="/guides/{s}">{o["h1"]}</a></li>' for s, o in GUIDES.items() if s != slug)
    inner = (f'<p class="crumb"><a href="/guides">Guides</a> ›</p><h1>{g["h1"]}</h1>{g["body"]()}'
             f'<h2>More guides</h2><ul>{more}</ul>')
    return make_response(_page(g["title"], f"/guides/{slug}", g["desc"], inner))
