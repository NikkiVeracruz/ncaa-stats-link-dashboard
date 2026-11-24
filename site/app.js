"use strict";
const $=id=>document.getElementById(id);
const labels={FBS:"FBS Football",FCS:"FCS Football",MBB:"Men's Basketball",WBB:"Women's Basketball"};
const reportLabels={game_center:"Official Game Center",box_score:"Official online box score",pdf_box_score:"Official PDF box score / gamebook"};
const official={FBS:"https://stats.ncaa.org/contests/scoreboards?division=11&sport_code=MFB",FCS:"https://stats.ncaa.org/contests/scoreboards?division=12&sport_code=MFB",MBB:"https://stats.ncaa.org/contests/scoreboards?division=1&sport_code=MBB",WBB:"https://stats.ncaa.org/contests/scoreboards?division=1&sport_code=WBB"};
let feed=null;
function node(tag,text,cls){const x=document.createElement(tag);if(text!==undefined)x.textContent=text;if(cls)x.className=cls;return x}
function link(label,url){try{const u=new URL(url);if(u.protocol!=="https:"||u.username||u.password)return null;const a=node("a",label,"link");a.href=u.href;a.target="_blank";a.rel="noopener noreferrer";return a}catch{return null}}
function addLink(parent,label,url){const a=link(label,url);if(a)parent.append(a)}
function localTime(v){try{return new Intl.DateTimeFormat("en-US",{timeZone:"America/New_York",hour:"numeric",minute:"2-digit",timeZoneName:"short"}).format(new Date(v))}catch{return ""}}
function matches(g,q){return [g.home_team,g.away_team,...Object.values(g.schools||{}).filter(Boolean).map(s=>s.name)].join(" ").toLowerCase().includes(q.toLowerCase())}
function gameCard(g){const e=node("article",undefined,"game");const state=g.completed?"Final":g.status_text; e.append(node("div",g.date_et+" · "+(g.state==="pre"?localTime(g.start_utc):state),"meta"));if(g.state==="in")e.append(node("div","Period "+(g.period??"—")+" · "+(g.clock??"—"),"live"));for(const side of ["away","home"]){const row=node("div",undefined,"team");row.append(node("span",g[side+"_team"]),node("strong",g[side+"_score"]??"—"));e.append(row)}if(g.neutral_site)e.append(node("small","Neutral site"));
const links=node("div",undefined,"links");for(const r of g.reports||[])addLink(links,(reportLabels[r.kind||"box_score"]||"Reviewed report")+" — "+r.school,r.url);for(const side of ["home","away"]){const s=g.schools?.[side];if(!s)continue;if(s.schedule_shortcut)addLink(links,g[side+"_team"]+" — school schedule",s.schedule_shortcut);addLink(links,g[side+"_team"]+" — athletics website",s.website)}for(const [sport,url] of Object.entries(g.scoreboards||{}))addLink(links,labels[sport]+" — NCAA scoreboard",url);e.append(links,node("small","Locate the matchup on "+g.date_et+". Open Game Center or a school schedule to locate the report. Links are optional; absence does not mean a report is unavailable."));return e}
function guide(sport){
 const football=sport==="FBS"||sport==="FCS", e=node("div",undefined,"guide");
 e.append(node("h3","Finding official "+labels[sport]+" reports"),node("p","This tracker is a shortcut for trained agents, not the official statistics source. Game tracking is independent of report availability. Links are added when reliably found; missing links never prevent archiving."));
 const entries=[
 ["School schedule","Opens that school's sport-specific schedule. Find the opponent and game date (Ctrl+F or Cmd+F can help). Select Game Center, Box Score, Stats, Gamebook or PDF Box Score. If the shortcut is unavailable, use Athletics Website."],
 ["Athletics website","Opens the school athletics homepage. Select "+(football?"Football":"the correct "+(sport==="MBB"?"men’s":"women’s")+" basketball sport")+", then Schedule. Find the matchup. Try the other school's website if needed."],
 ["Official Game Center","Opens the individual matchup page, which may be available before kickoff or tipoff. After the game, look for Game Info, Stats, Box Score, PDF Box Score, Gamebook or Downloads."],
 ["Official online box score","Opens the individual game's web statistics. Look for a PDF, Download, Printable Box Score or Gamebook option; some schools only publish an online box score."],
 ["Official PDF box score / gamebook","Opens a reviewed or automatically verified PDF link for this matchup. Confirm the teams, date and final score; use the relevant report sections."],
 ["NCAA scoreboard","Opens the official NCAA "+labels[sport]+" scoreboard. Choose the game date, find the matchup, then click Box Score. A gamebook PDF may not be offered there; try the school sites or usual resources."]];
 const dl=node("dl");for(const [title,body] of entries)dl.append(node("dt",title),node("dd",body));e.append(dl);
 e.append(node("p",football?"For player participation, check the complete Participation / Player Participation report, including starters and substitutes. No individual statistic does not mean no participation.":"For player participation, review minutes, DNP and substitutions. Zero minutes or a missing line alone does not prove nonparticipation."));
 if(sport==="WBB")e.append(node("p","Automatic PDF discovery is currently a limited women's basketball pilot for Vanderbilt, Iowa and Miami (FL). Other games retain school navigation and reviewed report links."));
 e.append(node("p","Optional link discovery targets: every 5 min in the first hour after completion is detected, every 15 min for the next three hours, then hourly through 24 hours. Only available, permitted sources are checked; not all links can be discovered automatically. Use the normal verification process when a link is missing."));
 e.append(node("p",football?"Current view: Thursday through Wednesday, rolling Thursday at 3 AM Eastern.":"Current view: yesterday, today and tomorrow, rolling daily at 3 AM Eastern."));
 addLink(e,"Open official "+labels[sport]+" scoreboard",official[sport]);return e
}
function groups(container,games,{showEmpty=false,filter=""}={}){
 const opened=new Set([...container.querySelectorAll("details[open]")].map(d=>d.dataset.sport));container.replaceChildren();
 if(!games.length&&!showEmpty){container.append(node("p","No matching games in the available data."));return}
 for(const [sport,label] of Object.entries(labels)){
  if(filter&&sport!==filter)continue;
  const rows=games.filter(g=>g.sports.includes(sport));
  if(!rows.length&&!showEmpty)continue;
  const d=node("details");d.dataset.sport=sport;d.open=opened.has(sport);
  d.append(node("summary",label+" ("+rows.length+")"),guide(sport));
  if(!rows.length)d.append(node("p","No games in this display window or matching the selected filters.","game"));
  for(const g of rows)d.append(gameCard(g));container.append(d)
 }
}
function render(){if(!feed){groups($("current"),[],{showEmpty:true});return}const sport=$("sport").value,status=$("status").value,query=$("search").value.trim();groups($("current"),feed.current.filter(g=>(!sport||g.sports.includes(sport))&&(!status||g.state===status)&&matches(g,query)),{showEmpty:true,filter:sport});const aq=$("archiveSearch").value.trim(),ad=$("archiveDate").value;if(aq||ad)groups($("archive"),feed.archive.filter(g=>(!sport||g.sports.includes(sport))&&(!ad||g.date_et===ad)&&matches(g,aq)));else $("archive").replaceChildren(node("p","Enter a team or date to show archived games."));$("official").replaceChildren();for(const [s,url] of Object.entries(feed.scoreboards))addLink($("official"),labels[s]+" official scoreboard",url);$("archiveStart").textContent="Archive begins "+feed.archive_start+"."}
let busy=false;
async function load(){if(busy)return;busy=true;try{const response=await fetch("feed.json",{cache:"no-store"});if(!response.ok)throw Error("Feed unavailable");const next=await response.json();if(!Array.isArray(next.current)||!Array.isArray(next.archive)||!next.scoreboards||!next.updated_at)throw Error("Invalid feed");feed=next;$("notice").textContent="Last successful data update: "+new Date(feed.updated_at).toLocaleString();render()}catch(e){$("notice").textContent=feed?"Refresh failed; displaying last successfully loaded data.":"Game data unavailable. Use official scoreboards until the feed is restored."}finally{busy=false}}
for(const id of ["search","sport","status","archiveSearch","archiveDate"])$(id).addEventListener("input",render);
$("refresh").addEventListener("click",load);render();load();setInterval(load,60000);
