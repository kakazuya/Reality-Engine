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
