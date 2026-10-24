# Writes frontend/src/watch/platform.css. Every selector starts with :is(#_pf,.pf-card): the id inside :is gives the
# platform cards a higher specificity than the app's theme rules, so a post keeps its real platform look in both themes.
import re
SRC = r'''
.pf-card{--pf-ink:#0F1419;--pf-dim:#65676B;--pf-line:#E4E6EB;--pf-blue:#0866FF;background:#fff;color:var(--pf-ink);border:1px solid #DBDBDB;border-radius:12px;overflow:hidden;font:14px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;text-align:left;box-shadow:0 10px 28px rgba(5,9,20,.18);min-width:0;display:flex;flex-direction:column}
.pf-card *{box-sizing:border-box;color:inherit;letter-spacing:normal;text-transform:none;font-family:inherit}
.pf-card b{font-weight:600}
.pf-card p{margin:0}
.pf-card svg{display:block;flex:none}
.pf-card header{display:flex;align-items:center;gap:10px;padding:12px 14px;background:transparent;border:0}
.pf-card .pf-who{display:flex;flex-direction:column;min-width:0;line-height:1.25}
.pf-card .pf-who b{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pf-card .pf-dim{color:var(--pf-dim);font-size:12.5px}
.pf-card .pf-end{margin-left:auto;color:var(--pf-dim)}
.pf-card .pf-ico{display:inline-flex;vertical-align:-2px}
.pf-card .pf-ico svg{width:12px;height:12px}
.pf-card .pf-avatar{display:inline-flex;flex:none;overflow:hidden;border-radius:50%;background:#F0F2F5}
.pf-card .pf-avatar.square{border-radius:6px}
.pf-card .pf-avatar .w-logo{border-radius:inherit!important;border:0!important;box-shadow:none!important;background:#F0F2F5;color:#1C1E21}
.pf-card .pf-text{padding:0 14px 12px;white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px;line-height:1.42;color:var(--pf-ink)}
.pf-card .pf-more{background:none;border:0;padding:0;margin:0;font:inherit;color:var(--pf-dim);cursor:pointer;font-weight:600;min-height:0;box-shadow:none}
.pf-card .pf-more:hover{text-decoration:underline;background:none}
.pf-card .pf-media{position:relative;width:100%;max-width:100%;background:linear-gradient(110deg,#EFF1F4 30%,#F7F8FA 50%,#EFF1F4 70%);background-size:250% 100%;animation:pf-wait 1.4s linear infinite;overflow:hidden}
.pf-card .pf-media a{display:block;width:100%;height:100%}
.pf-card .pf-media img{width:100%;height:100%;object-fit:cover;display:block;border:0;border-radius:0;max-width:none}
.pf-card .pf-media-gone{position:absolute;inset:0;display:grid;place-items:center;color:#B0B3B8;font-size:13px;background:#F0F2F5}
.pf-card .pf-reel{position:absolute;top:10px;right:10px;color:#fff;filter:drop-shadow(0 1px 3px rgba(0,0,0,.5))}
.pf-card .pf-count{position:absolute;top:10px;right:10px;background:rgba(18,18,18,.7);color:#fff;font-size:12px;padding:3px 8px;border-radius:12px}
.pf-card .pf-nav{position:absolute;top:50%;transform:translateY(-50%);width:28px;height:28px;min-height:0;padding:0;border-radius:50%;border:0;background:rgba(255,255,255,.85);color:#262626;font:600 18px/26px sans-serif;cursor:pointer;box-shadow:0 1px 4px rgba(0,0,0,.25)}
.pf-card .pf-nav.prev{left:8px}.pf-card .pf-nav.next{right:8px}
.pf-card .pf-nav:disabled{display:none}
.pf-card .pf-dots{position:absolute;bottom:10px;left:0;right:0;display:flex;justify-content:center;gap:4px}
.pf-card .pf-dots i{width:6px;height:6px;border-radius:50%;background:rgba(255,255,255,.5)}
.pf-card .pf-dots i.on{background:#fff}
.pf-card .pf-bar{display:flex;justify-content:space-around;border-top:1px solid var(--pf-line);margin:0 12px;padding:4px 0}
.pf-card .pf-bar span{display:inline-flex;align-items:center;gap:6px;padding:8px 6px;color:var(--pf-dim);font-weight:600;font-size:13.5px}
.pf-card .pf-bar svg{width:19px;height:19px}
.pf-card .pf-reacts{display:inline-flex;align-items:center;color:var(--pf-dim);font-size:13px}
.pf-card .pf-reacts i{width:18px;height:18px;border-radius:50%;display:inline-grid;place-items:center;color:#fff;border:2px solid #fff;margin-right:-4px;font-style:normal;font-size:9px}
.pf-card .pf-reacts i:last-of-type{margin-right:6px}
.pf-card .pf-reacts i svg{width:10px;height:10px}
.pf-card .pf-reacts i.like{background:var(--pf-blue)}
.pf-card .pf-reacts i.love{background:#F33E58}
.pf-card .pf-reacts i.clap{background:#6DAE4F}
.pf-card .pf-btn{display:inline-flex;align-items:center;justify-content:center;padding:7px 14px;border-radius:6px;background:#E4E6EB;color:#050505;font-weight:600;font-size:13.5px;white-space:nowrap}

.pf-ig{border-radius:8px;--pf-ink:#000;--pf-dim:#737373}
.pf-ig header{padding:10px 12px;gap:8px}
.pf-ig header b{font-size:14px}
.pf-ig .pf-ring{padding:2px;border-radius:50%;background:conic-gradient(from 210deg,#FEDA75,#FA7E1E,#D62976,#962FBF,#4F5BD5,#FEDA75);display:inline-flex}
.pf-ig .pf-ring .pf-avatar{border:2px solid #fff}
.pf-ig .pf-ig-actions{display:flex;gap:14px;padding:10px 12px 6px;color:#000}
.pf-ig .pf-ig-actions svg{width:24px;height:24px}
.pf-ig .pf-ig-body{padding:0 12px 12px;display:flex;flex-direction:column;gap:4px}
.pf-ig .pf-likes{font-size:14px}
.pf-ig .pf-text{padding:0}
.pf-ig .pf-line{font-size:14px}
.pf-ig .pf-date{font-size:10.5px;color:var(--pf-dim);text-transform:uppercase;letter-spacing:.2px}

.pf-fb{--pf-ink:#050505;--pf-dim:#65676B;border-color:#DADDE1}
.pf-fb header b{font-size:15px}
.pf-fb .pf-text{font-size:15px}
.pf-fb .pf-fb-stats{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:10px 14px}

.pf-li{--pf-ink:rgba(0,0,0,.9);--pf-dim:rgba(0,0,0,.6);--pf-blue:#0A66C2;border-color:#E0DFDC;border-radius:10px}
.pf-li header{align-items:flex-start}
.pf-li .pf-follow{color:#0A66C2;font-weight:600;font-size:14px}
.pf-li .pf-li-stats{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:8px 14px}
.pf-li .pf-reacts i.like{background:#378FE9}
.pf-li .pf-reacts i.love{background:#DF704D}

.pf-ad{--pf-ink:#1C2B33;--pf-dim:#465A69;border-color:#CBD2D9;border-radius:10px;background:#fff}
.pf-ad .pf-ad-meta{display:flex;flex-direction:column;gap:3px;padding:12px 14px;font-size:13px;border-bottom:1px solid #CBD2D9}
.pf-ad .pf-status{display:inline-flex;align-items:center;gap:6px;font-weight:600;color:#465A69}
.pf-ad .pf-status::before{content:"";width:8px;height:8px;border-radius:50%;background:#8595A4}
.pf-ad .pf-status.on{color:#1B7A3F}
.pf-ad .pf-status.on::before{background:#31A24C;box-shadow:0 0 0 3px #31A24C33}
.pf-ad .pf-plats{display:inline-flex;align-items:center;gap:4px;color:var(--pf-dim)}
.pf-ad .pf-plats i{display:inline-grid;place-items:center;width:18px;height:18px;border-radius:50%;background:#1C2B33;color:#fff;font:700 9px/1 sans-serif}
.pf-ad .pf-ad-post{margin:12px;border:1px solid #DADDE1;border-radius:8px;overflow:hidden}
.pf-ad .pf-ad-cta{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:10px 12px;background:#F0F2F5}
.pf-ad .pf-ad-cta>span:first-child{display:flex;flex-direction:column;min-width:0}
.pf-ad .pf-ad-cta small{font-size:11.5px;color:var(--pf-dim)}
.pf-ad .pf-ad-cta b{font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

.pf-web{border-color:#C9CDD4;border-radius:10px;background:#fff}
.pf-web .pf-chrome{display:flex;align-items:center;gap:10px;padding:8px 10px;background:#E9EBEF;border-bottom:1px solid #D3D6DC}
.pf-web .pf-lights{display:flex;gap:6px}
.pf-web .pf-lights i{width:10px;height:10px;border-radius:50%;background:#FF5F57}
.pf-web .pf-lights i:nth-child(2){background:#FEBC2E}.pf-web .pf-lights i:nth-child(3){background:#28C840}
.pf-web .pf-url{flex:1;min-width:0;display:flex;align-items:center;gap:6px;background:#fff;border-radius:7px;padding:4px 10px;font-size:12px;color:#3C4043;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pf-web .pf-url .pf-ico svg{width:11px;height:11px}
.pf-web .pf-site{display:flex;flex-direction:column}
.pf-web nav{display:flex;align-items:center;gap:8px;padding:10px 14px;border-bottom:1px solid #EEF0F3;font-size:13px}
.pf-web nav>b{white-space:nowrap}
.pf-web .pf-navlinks{margin-left:auto;display:flex;gap:12px;color:#5F6368;font-size:12px;min-width:0;overflow:hidden;white-space:nowrap}
.pf-web .pf-hero{position:relative;padding:26px 18px;display:flex;flex-direction:column;gap:10px;background:linear-gradient(135deg,#F4F6FB,#E8EDF7);min-height:150px;justify-content:flex-end}
.pf-web .pf-hero.pic{background-size:cover;background-position:center;color:#fff}
.pf-web .pf-hero.pic::before{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.05),rgba(0,0,0,.65))}
.pf-web .pf-hero>*{position:relative}
.pf-web .pf-kind{align-self:flex-start;font-size:11px;font-weight:600;padding:2px 8px;border-radius:10px;background:rgba(0,0,0,.08)}
.pf-web .pf-hero.pic .pf-kind{background:rgba(255,255,255,.25)}
.pf-web h4{margin:0;font-size:21px;line-height:1.2;font-weight:700;text-wrap:balance;color:inherit}
.pf-web .pf-site-btns{display:flex;gap:8px;flex-wrap:wrap}
.pf-web .pf-site-btns span{padding:7px 14px;border-radius:8px;background:#1A73E8;color:#fff;font-size:13px;font-weight:600}
.pf-web .pf-site-btns span.ghost{background:rgba(255,255,255,.9);color:#1A73E8}
.pf-web .pf-prices{display:grid;grid-template-columns:repeat(auto-fit,minmax(90px,1fr));gap:8px;padding:12px 14px}
.pf-web .pf-prices span{display:flex;flex-direction:column;border:1px solid #E3E6EB;border-radius:8px;padding:8px 10px}
.pf-web .pf-prices small{font-size:11.5px;color:#5F6368}
.pf-web .pf-prices b{font-size:15px}
.pf-web .pf-chips{display:flex;flex-wrap:wrap;gap:6px;padding:12px 14px 4px}
.pf-web .pf-chips span{font-size:12px;padding:4px 10px;border-radius:14px;background:#F1F3F4;color:#3C4043}
.pf-web .pf-clients{display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px;padding:10px 14px 14px;color:#80868B}
.pf-web .pf-clients small{width:100%;font-size:11px;text-transform:uppercase;letter-spacing:.6px}
.pf-web .pf-clients b{font-size:13px;color:#5F6368}

.pf-search{--pf-ink:#202124;--pf-dim:#4D5156;border-color:#DADCE0;border-radius:10px;padding-bottom:12px;font-family:Arial,sans-serif}
.pf-search .pf-tab{align-self:flex-start;margin:10px 14px 0;font-size:12px;color:#1A73E8;border-bottom:2px solid #1A73E8;padding-bottom:3px}
.pf-search header{padding:10px 14px 4px}
.pf-search .pf-fav{width:26px;height:26px;border-radius:50%;display:grid;place-items:center;background:#F1F3F4;border:1px solid #DADCE0;font-weight:700;font-size:12px;color:#5F6368}
.pf-search .pf-who b{font-size:14px;font-weight:400}
.pf-search .pf-who .pf-dim{font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pf-search .pf-title{display:block;padding:2px 14px 4px;font-size:19px;line-height:1.3;color:#1A0DAB;text-decoration:none}
.pf-search a.pf-title:hover{text-decoration:underline}
.pf-search .pf-text{padding:0 14px;font-size:14px;color:#4D5156}

.pf-jobs{border-color:#E0DFDC;border-radius:10px;--pf-ink:rgba(0,0,0,.9);--pf-dim:rgba(0,0,0,.6)}
.pf-jobs ul{list-style:none;margin:0;padding:0 14px 12px;display:flex;flex-direction:column}
.pf-jobs li{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:10px 0;border-top:1px solid #EBEBEB}
.pf-jobs li b{color:#0A66C2}
.pf-jobs .pf-btn{background:#fff;border:1px solid #0A66C2;color:#0A66C2;border-radius:16px;padding:4px 12px}
.pf-jobs>p{padding:0 14px 12px}

.pf-card .pf-tools{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 14px;border-top:1px dashed var(--pf-line);font-size:12px;color:var(--pf-dim);background:#FAFAFA;margin-top:auto}
.pf-card .pf-tools a{color:#1A73E8;text-decoration:none;font-weight:600}
.pf-card .pf-tools details{position:relative}
.pf-card .pf-tools summary{cursor:pointer;color:var(--pf-dim);font-weight:600}
.pf-card .pf-tools pre,.pf-card .pf-tools dl{max-height:260px;overflow:auto;white-space:pre-wrap;font:12px/1.5 ui-monospace,monospace;color:#3C4043;background:#fff;border:1px solid var(--pf-line);border-radius:8px;padding:8px;margin:8px 0 0}
.pf-card .pf-tools dl div{display:grid;grid-template-columns:110px minmax(0,1fr);gap:8px;padding:3px 0}
.pf-card .pf-tools dt{color:var(--pf-dim)}
.pf-card .pf-tools dd{margin:0;overflow-wrap:anywhere}
.pf-card.live{outline:2px solid #31A24C;outline-offset:-2px}
.pf-card .pf-from{display:flex;align-items:center;gap:6px;padding:8px 14px 0;font-size:11.5px;color:var(--pf-dim);font-weight:600}
.pf-web .pf-secs{display:flex;flex-direction:column;border-top:1px solid #EEF0F3}
.pf-web .pf-pick{display:flex;flex-wrap:wrap;gap:6px;padding:10px 14px 0}
.pf-web .pf-pick button{min-height:28px;padding:0 10px;border-radius:14px;border:1px solid #D3D6DC;background:#fff;color:#3C4043;font-size:12px;cursor:pointer;box-shadow:none}
.pf-web .pf-pick button.on{background:#1A73E8;border-color:#1A73E8;color:#fff}
.pf-web .pf-sec{padding:12px 14px;border-bottom:1px solid #EEF0F3;display:flex;flex-direction:column;gap:6px}
.pf-web .pf-sec h5{margin:0;font-size:15px;font-weight:700;color:#202124;line-height:1.3}
.pf-web .pf-sec p{font-size:13px;color:#4D5156;line-height:1.45}
.pf-web .pf-pics{display:grid;grid-template-columns:repeat(auto-fill,minmax(92px,1fr));gap:8px;margin-top:4px}
.pf-web .pf-pic{margin:0;display:flex;flex-direction:column;gap:4px;min-width:0}
.pf-web .pf-pic a{display:grid;place-items:center;aspect-ratio:4/3;background:#F6F7F9;border:1px solid #EEF0F3;border-radius:8px;overflow:hidden}
.pf-web .pf-pic img{max-width:100%;max-height:100%;object-fit:contain;display:block;border:0}
.pf-web .pf-pic.photo img{width:100%;height:100%;object-fit:cover}
.pf-web .pf-pic figcaption{display:flex;flex-direction:column;gap:2px;font-size:11px;line-height:1.3;color:#5F6368}
.pf-web .pf-pic figcaption b{align-self:flex-start;font-size:10.5px;font-weight:600;border-radius:5px;padding:1px 6px;background:#E8F0FE;color:#1967D2}
.pf-web .pf-pic figcaption b.client_logo{background:#E6F4EA;color:#137333}
.pf-web .pf-pic figcaption b.partner_logo{background:#FEF7E0;color:#B06000}
.pf-web .pf-pic figcaption b.brand_logo{background:#F3E8FD;color:#8430CE}
.pf-web .pf-pic figcaption b.team{background:#FCE8E6;color:#C5221F}
.pf-web .pf-pic figcaption span{overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.pf-web .pf-secmore{background:none;border:0;padding:10px 14px;color:#1A73E8;font-size:13px;font-weight:600;cursor:pointer;text-align:left;min-height:0;box-shadow:none}

.pf-card .pf-blank{display:grid;place-items:center;background:linear-gradient(135deg,#18264A,#0E3A4A);animation:none;color:#fff;padding:18px;text-align:center;font:600 17px/1.3 -apple-system,"Segoe UI",sans-serif}
.pf-card .pf-blank span{max-width:22ch}
.pf-card .pf-slides{list-style:none;margin:8px 0 0;padding:0 14px 12px;display:flex;gap:8px;overflow-x:auto;scroll-snap-type:x mandatory}
.pf-ig .pf-slides{padding:8px 0 4px}
.pf-card .pf-slides li{flex:0 0 150px;scroll-snap-align:start;border:1px solid var(--pf-line);border-radius:10px;padding:10px;display:flex;flex-direction:column;gap:4px;background:#F7F8FA;font-size:12.5px;line-height:1.35}
.pf-card .pf-slides small{color:var(--pf-dim);font-size:11px}
.pf-card .pf-slides span{color:var(--pf-dim)}
.pf-story{background:#000;color:#fff;border-color:#000;position:relative;max-width:300px}
.pf-story header{position:absolute;top:14px;left:0;right:0;z-index:2;color:#fff;padding:8px 12px}
.pf-story header .pf-dim{color:#ffffffb0}
.pf-story .pf-story-bars{position:absolute;top:8px;left:10px;right:10px;z-index:3;display:flex;gap:4px}
.pf-story .pf-story-bars i{flex:1;height:2.5px;border-radius:2px;background:#ffffff55}
.pf-story .pf-story-bars i.on{background:#fff}
.pf-story .pf-story-frames{position:absolute;left:12px;right:12px;bottom:16px;z-index:2;display:flex;flex-direction:column;gap:8px}
.pf-story .pf-story-frames p{background:#000000a0;border-radius:12px;padding:8px 10px;display:flex;flex-direction:column;gap:2px;font-size:13px}
.pf-story .pf-story-frames p span{color:#ffffffc0;font-size:12px}
.pf-card .pf-grid{display:grid;grid-template-columns:1fr 1fr;gap:3px;background:#fff}
.pf-card .pf-grid .pf-tile{position:relative;aspect-ratio:1/1;overflow:hidden;background:linear-gradient(110deg,#EFF1F4 30%,#F7F8FA 50%,#EFF1F4 70%);background-size:250% 100%;animation:pf-wait 1.4s linear infinite}
.pf-card .pf-grid .pf-tile.wide{grid-column:span 2;aspect-ratio:2/1}
.pf-card .pf-grid.one .pf-tile{grid-column:span 2;aspect-ratio:auto;min-height:120px;animation:none;background:#F0F2F5}
.pf-card .pf-grid.one .pf-tile img{height:auto;max-height:620px;object-fit:contain}
.pf-card .pf-grid .pf-tile a{display:block;width:100%;height:100%}
.pf-card .pf-grid .pf-tile img{width:100%;height:100%;object-fit:cover;display:block;border:0;border-radius:0;max-width:none}
.pf-card .pf-grid .pf-tile .pf-plus{position:absolute;inset:0;display:grid;place-items:center;background:rgba(0,0,0,.45);color:#fff;font-size:28px;font-weight:600;pointer-events:none}
.pf-card .pf-grid .pf-tile .pf-reel{position:absolute;top:10px;right:10px}
.pf-card .pf-versions{display:flex;flex-direction:column;gap:6px;padding:10px 14px 4px;border-top:1px solid var(--pf-line)}
.pf-card .pf-versions small{color:var(--pf-dim);font-size:12px}
.pf-card .pf-versions span{display:flex;gap:6px;overflow-x:auto}
.pf-card .pf-versions button{flex:none;width:54px;height:54px;padding:0;min-height:0;border:2px solid transparent;border-radius:6px;overflow:hidden;background:#F0F2F5;cursor:pointer}
.pf-card .pf-versions button.on{border-color:var(--pf-blue)}
.pf-card .pf-versions img{width:100%;height:100%;object-fit:cover;display:block;max-width:none;border-radius:0}
.pf-web .pf-cover{display:block;width:100%;max-height:260px;object-fit:cover;border-radius:0;max-width:none}
.pf-web .pf-views{display:flex;gap:4px;padding:8px 10px;background:#F8F9FA;border-bottom:1px solid #E8EAED}
.pf-web .pf-views button{all:unset;cursor:pointer;padding:5px 12px;border-radius:14px;font-size:12px;font-weight:600;color:#5F6368}
.pf-web .pf-views button.on{background:#E8F0FE;color:#1967D2}
.pf-web .pf-views button:focus-visible{outline:2px solid #1A73E8}
.pf-web .pf-shot{position:relative;max-height:420px;overflow:hidden;background:#fff}
.pf-web .pf-shot.tall{max-height:2400px;overflow:auto}
.pf-web .pf-shot img{display:block;width:100%;height:auto;max-width:none;border-radius:0}
.pf-web .pf-shot:not(.tall)::after{content:"";position:absolute;inset:auto 0 0;height:90px;background:linear-gradient(transparent,#fff);pointer-events:none}
.pf-web .pf-shot-tools{position:sticky;bottom:0;display:flex;justify-content:center;gap:8px;padding:8px;z-index:1}
.pf-web .pf-shot:not(.tall) .pf-shot-tools{position:absolute;left:0;right:0;bottom:6px}
.pf-web .pf-shot-tools button,.pf-web .pf-shot-tools a{all:unset;cursor:pointer;padding:6px 14px;border-radius:16px;font-size:12px;font-weight:600;background:#202124;color:#fff;box-shadow:0 4px 12px rgba(0,0,0,.25)}
.pf-web .pf-shot-tools a{background:#fff;color:#202124}
.pf-search .pf-search-body{display:flex;gap:12px;align-items:flex-start;padding-right:14px}
.pf-search .pf-search-body .pf-text{flex:1;min-width:0}
.pf-search .pf-search-pic{width:104px;height:104px;object-fit:cover;border-radius:8px;flex:none;max-width:none}
'''
P = ':is(#_pf,.pf-card)'
# The wrapper under each card (original link, full text, saved fields) follows the app's own theme.
WRAP = '''
.pf-item{display:flex;flex-direction:column;gap:8px;min-width:0;break-inside:avoid;margin-bottom:22px}
.w-evidence-grid:has(>.pf-item){display:block;columns:320px;column-gap:16px}
@keyframes pf-wait{to{background-position:-150% 0}}
@media (prefers-reduced-motion:reduce){.pf-media{animation:none!important}}
.pf-under{display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px;padding:0 4px;font-size:12px}
.pf-under-label{font-weight:600;opacity:.75}
.pf-under details{width:100%}
.pf-under summary{cursor:pointer;opacity:.8}
.pf-under pre{max-height:260px;overflow:auto;white-space:pre-wrap;font-size:12px}
'''
out = []
for block in re.findall(r'([^{}]+)\{([^{}]*)\}', SRC):
    sel, body = block
    sel = sel.strip()
    parts = []
    for s in sel.split(','):
        s = s.strip()
        m = re.match(r'(\.pf-card|\.pf-[a-z]+)(.*)', s)
        head, rest = m.group(1), m.group(2)
        if head == '.pf-card':
            parts.append(P + rest)
        else:   # .pf-ig etc. are on the card itself
            parts.append(P + head + rest)
    out.append(','.join(parts) + '{' + body.strip() + '}')
open(__import__('pathlib').Path(__file__).resolve().parents[1] / 'frontend/src/watch/platform.css', 'w').write(
    '/* Generated by scripts/platform_css.py: scraped items in their real platform look (Instagram, Facebook, LinkedIn,\n'
    '   Meta Ad Library, a browser window, a search result). Edit that script, not this file. */\n' + WRAP.strip() + '\n' + '\n'.join(out) + '\n')
print(len(out))
