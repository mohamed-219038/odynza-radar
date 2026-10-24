import m0Icon from "./icons/m0-magnifier.png";
import m1Icon from "./icons/m1-chess-pawn.png";
import m2Icon from "./icons/m2-clapper.png";

/** The Odynza Radar mark ("Sweep O"): the O of Odynza as a radar, with a sweep arm and one rival blip.
    Decorative; the name is always written next to it. */
export function Mark({ size = 30, spinning = false }: { size?: number; spinning?: boolean }) {
  return (
    <svg className={"odz-mark" + (spinning ? " spin" : "")} width={size} height={size} viewBox="0 0 40 40" aria-hidden="true">
      <circle cx="20" cy="20" r="16" fill="none" stroke="currentColor" strokeWidth="4.4" />
      <g className="odz-sweep-arm">
        <path d="M20 20 L33.5 11.4 A16 16 0 0 0 20 4 Z" fill="currentColor" fillOpacity=".28" />
        <path d="M20 20 L33.5 11.4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </g>
      <circle cx="26.8" cy="26.2" r="2.5" className="odz-blip" />
      <circle cx="20" cy="20" r="1.9" fill="currentColor" />
    </svg>
  );
}

/** The big radar on the sign-in page: thin rings and a slow sweep, in the Sweep O colours. */
export function RadarArt({ size = 340 }: { size?: number }) {
  return (
    <svg className="odz-mark spin" width={size} height={size} viewBox="0 0 40 40" aria-hidden="true">
      <circle cx="20" cy="20" r="17" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="20" cy="20" r="11" fill="none" stroke="currentColor" strokeOpacity=".4" strokeWidth=".8" />
      <circle cx="20" cy="20" r="5" fill="none" stroke="currentColor" strokeOpacity=".3" strokeWidth=".6" />
      <g className="odz-sweep-arm">
        <path d="M20 20 L34.4 11 A17 17 0 0 0 20 3 Z" fill="currentColor" fillOpacity=".18" />
        <path d="M20 20 L34.4 11" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
      </g>
      <circle cx="27.5" cy="27" r="1.4" className="odz-blip" />
      <circle cx="12" cy="15" r="1" fill="#F5A35C" />
      <circle cx="20" cy="20" r="1.2" fill="currentColor" />
    </svg>
  );
}

/** The Odynza Radar wordmark: the Sweep O mark, "odynza" and the RADAR tag. */
export function Brand({ size = 30 }: { size?: number }) {
  return (
    <div className="odz-brand">
      <Mark size={size} />
      <span>
        odynza<em className="odz-wordtag">radar</em>
      </span>
    </div>
  );
}

/** The agent marks ("C Studio", Odynza's pick): 3D icons from Microsoft's Fluent UI Emoji set (MIT, see
    icons/LICENSE.txt). M0 is a magnifier inspecting rivals, M1 a chess pawn for strategy moves, M2 a clapper board for
    content. The code tag colour comes from CSS. */
const AGENT_ICON = { M0: m0Icon, M1: m1Icon, M2: m2Icon };

export function AgentMark({ code, size = 34 }: { code: "M0" | "M1" | "M2"; size?: number }) {
  return (
    <span className={"odz-agent-code " + code.toLowerCase()} style={{ width: size, height: size }} aria-hidden="true">
      <img src={AGENT_ICON[code]} width={size} height={size} alt="" draggable={false} />
      <em>{code}</em>
    </span>
  );
}
