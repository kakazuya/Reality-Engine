# Shivam's rulings in his own words (append-only, never edited or trimmed)

Each entry: date, the rule as recorded in `tasks/RULINGS.md`, and Shivam's words as he gave them. `python -m
reality_engine.scripts.ruling add ... --quote "<his words>"` appends here. Earlier rulings: `docs/rulings/RULINGS_full_2026-11-08.md`
and `docs/rulings/RULINGS_FULL.md` (every earlier wording).

## 2026-11-26 | Reasoning ladder
Rule: errands -> gemini-worker Gemma 4 31B/26B if quick; harder -> DeepSeek off-peak, agy Hydrogen in peak; DeepSeek
weak or failing rounds -> Hydrogen high; higher reasoning/review -> Opus medium; hardest only -> Neon 4 high/xhigh,
sparingly.
> so here is the standing rule in terms of reasoning now, running simple errands go to gemini mcp worker which can run
> gemini 4 31B or 26B models if they are responding and quick enough -> running slightly higher reasoning tasks on
> deepseek if it's off peak and hydrogen if it's peak time -> even if if's off peak and deepseek's output quality is
> not good enough or failing repeatedly rounds then use hydrogen high -> if it needs even higher reasoning and review
> then do it yourselves (Opus at medium) -> for even higher reasoning/review tasks use Neon 4 high or xhigh (use it
> sparsingly when even you can figure out the work)

## 2026-11-26 | Question search on Flash 3.8, Neon on the agy account
> don't use argon, use 3.8 flash while it lifetime isn't ending for searching questions
> you can set up Neon on the same account on which current agy is running now

## 2026-11-26 | gemini-worker limits
> gemini worker mcp is built but hydrogen and other models won't be much useful there as requests per day are 20
> only, Gemini 4 31B is only useful with good enough limits

## 2026-11-26 | Never block reading
Rule: all doc types read and load; a graded sample >10% W+J loads unverified; block only if >10% of the database is
corrupt; Claude reviews and improves.
> go ahead, from now onwards you don't cockblock the readings, you just keep a watch on how to improve the database
> already present and the ones that are yet to be built, pehle system banne toh de, tu 4 mhine se 100 bricks m 2
> kharab hai bolke poora ghar hi nhi banne de rha hai 4 mhine se sasura. Aage se khali consultancy and review and
> improvement ka kaam kar blocking ka kaam tbhi jab 10% se jyada database corrupt hojaye

## 2026-11-26 | The database is never final
> since there are new models dropped every other week on opencode go and other gateways it's not like that the
> database is gonna be set in stone, we can keep on reviewing adding enhancing deleting modifying parts of the
> database all the time, plan the architecture with that in mind. It's not gonna be a one time setup and is a
> continous process and same goes for retrieval and analyses tools and methods

## 2026-11-26 | Read provenance on every row
Rule: rows store read_model, read_gateway, read_harness, prompt_fp, read_at.
> इसमें उसका नाम भी लिख लेना जिस एआई मॉडल ने रीड किया है डेटाबेस, तो पता रहेगा कि हमने कौन से मॉडल से रीड करवाया था,
> कौन सी डेट को रीड करवाया था ... अलग से एंट्री दो कॉलम्स की कि कौन से मॉडल ने रीड किया था, कौन से गेटवे से रीड हुआ था।
> ओपन कोड गो था, ओपन कोड जेन था, किलो गेटवे था कि कोई और गेटवे था, कौन सा हार्नेस था ... दिस इज लाइक अ मेटा डेटा।
> ... जब आगे सस्ते हो जाएंगे और मॉडल्स ... हम पूरा डेटाबेस को रिवैम्प कर पाएंगे आराम से। इसीलिए रॉ डेटाबेस हमने
> स्टोर करके रखा हुआ है गूगल ड्राइव में

## 2026-11-26 | Two copies of every capped file; skills for the rules
> you create skills for all these, so it is easier for us to load skills directly ... since markdown files become
> bigger, you cut out them and dilute the messages to keep it under the 8,000 character limits. I don't want that.
> Going forward, you maintain two separate copies of the markdown files, one for you to read into each session, and
> another for the whole toolings. So whenever we need to look at the exact set rules earlier, you have the copy handy.

## 2026-11-26 20:30 | Stop operations by 08:00 IST Fri 27 Nov, then cleanup only (one-time, T-245)
Rule: all operations stop by 08:00 IST Fri 27 Nov (Eagle stops hy4 loops 07:45, Wolf fallback 08:00); afterwards only
cleanup - data-heavy files to Drive, keep essentials on the MSI - so it runs as a lean cloud box from 10:00.
> After EOD today, Start uploading the raw sources onto gdrive and wrapping up everything on the cloud. so that by 10 am
> IST tomorrow, we are good to close this laptop and it stays as a cloud box from remote desktop by my hyderabad
> computer. Leave the data onto the cloud reast scripts and other environment variables can be kept, just that the data
> heavy files are moved on Gdrive so the SSD and HDD remains lean on the laptop by 10 am friday IST
> ok, stop the operations by 8 am IST tomorrow and focus the energy afterwards, on cleaning the operations and only
> keeping the essentials on this machine

## 2026-11-27 01:50 | raw\user_research to Drive too (replaces "kept local", 7 Nov)
Rule: `raw\user_research` (member videos, screen recordings; 814 files, 32.8 GB) is uploaded and hash-checked like all raw.
> Krde upload isko bhi

## 2026-11-27 11:15 | Grade steady outputs every 5th checkpoint (T-246)
Rule: an hy4 output whose last 2 grades passed (today transcripts, decks) is graded every 5th checkpoint; annual reports, results and anything just fixed or failing are graded at every checkpoint.
Wolf's recommendation he answered: "grade every 5th checkpoint for transcripts and decks, and every checkpoint for annual reports and results. Shall I set that up?"
> Ok, you have 30 min to update code and push merge
