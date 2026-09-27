import InterfaceIcon from "./InterfaceIcon";

const MARQUEE_ITEMS = [
  ["sparkles", "TABIKO"],
  ["spice", "SPICY"],
  ["plate", "LOCAL"],
  ["chinese", "MESSY"],
  ["coffee", "COFFEE"],
  ["sparkles", "FRESH"],
  ["comfort", "COMFORT"],
  ["date", "DATE NIGHT"],
  ["wrap", "STREET FOOD"],
];

export function FestivalMarquee() {
  const repeated = [...MARQUEE_ITEMS, ...MARQUEE_ITEMS];
  return (
    <div className="festival-marquee" aria-hidden="true">
      <div className="festival-marquee__track">
        {repeated.map(([icon, label], index) => (
          <span key={`${label}-${index}`}>
            <b><InterfaceIcon name={icon} size={17} strokeWidth={2.2} /></b> {label} <i>✦</i>
          </span>
        ))}
      </div>
    </div>
  );
}

export function HeroCollage() {
  return (
    <div className="hero-collage" aria-hidden="true">
      <span className="festival-sticker festival-sticker--spicy">
        <InterfaceIcon name="spice" size={20} /> FULL TASTE
      </span>
      <span className="festival-sticker festival-sticker--local">TABLE STAKES</span>
      <span className="festival-sticker festival-sticker--rating">
        <b>4.8</b> ★<small>LOCAL ENERGY</small>
      </span>
      <span className="festival-doodle festival-doodle--star">✦</span>
      <span className="festival-doodle festival-doodle--squiggle">〰</span>
      <span className="festival-food-sticker festival-food-sticker--one">
        <InterfaceIcon name="comfort" size={38} />
      </span>
      <span className="festival-food-sticker festival-food-sticker--two">
        <InterfaceIcon name="chinese" size={38} />
      </span>
      <span className="festival-food-sticker festival-food-sticker--three">
        <InterfaceIcon name="wrap" size={38} />
      </span>
    </div>
  );
}

export function FestivalConfetti() {
  return (
    <div className="festival-confetti" aria-hidden="true">
      {Array.from({ length: 18 }, (_, index) => (
        <i key={index} />
      ))}
    </div>
  );
}
