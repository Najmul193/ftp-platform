import { createContext, useContext } from "react";

/**
 * The pixel height a chart may use while its card is full screen, or null
 * while the card sits normally on the page.
 *
 * A concrete number rather than "100%": a percentage height has to resolve
 * against an ancestor with a definite height, and the cards nest charts
 * several wrappers deep inside flex items whose computed height is `auto`.
 * The card measures the space it actually has and passes it down, so the
 * chart never depends on that chain resolving.
 */
export const ExpandedHeight = createContext<number | null>(null);

export const useExpandedHeight = () => useContext(ExpandedHeight);
