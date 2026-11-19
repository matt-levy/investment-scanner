export function europeanOptionValue(kind: "call" | "put", spot: number, strike: number, years: number, volatility: number, rate: number, dividend: number): number {
  const intrinsic = () => Math.max(kind === "call" ? spot - strike : strike - spot, 0);
  if (years <= 0) return intrinsic();
  const ds = spot * Math.exp(-dividend * years);
  const dk = strike * Math.exp(-rate * years);
  if (spot <= 0) return kind === "call" ? 0 : dk;
  if (volatility <= 0) return Math.max(kind === "call" ? ds - dk : dk - ds, 0);
  const sd = volatility * Math.sqrt(years);
  const d1 = (Math.log(spot / strike) + (rate - dividend + .5 * volatility ** 2) * years) / sd;
  const d2 = d1 - sd;
  // Abramowitz-Stegun approximation to the normal CDF.
  const cdf = (x: number) => {
    const t = 1 / (1 + .2316419 * Math.abs(x));
    const density = Math.exp(-x * x / 2) / Math.sqrt(2 * Math.PI);
    const upper = density * t * (.319381530 + t * (-.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
    return x >= 0 ? 1 - upper : upper;
  };
  return Math.max(0, kind === "call" ? ds * cdf(d1) - dk * cdf(d2) : dk * cdf(-d2) - ds * cdf(-d1));
}
