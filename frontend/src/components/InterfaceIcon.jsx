const ICONS = {
  sparkles: `<path d="M12 2l1.4 4.1L17.5 7.5l-4.1 1.4L12 13l-1.4-4.1-4.1-1.4 4.1-1.4L12 2Z"/><path d="M19 14l.8 2.2L22 17l-2.2.8L19 20l-.8-2.2L16 17l2.2-.8L19 14Z"/><path d="M5 13l.7 1.8 1.8.7-1.8.7L5 18l-.7-1.8-1.8-.7 1.8-.7L5 13Z"/>`,
  "chevron-down": `<path d="M6 9l6 6 6-6"/>`,
  "arrow-right": `<path d="M5 12h14M14 7l5 5-5 5"/>`,
  check: `<path d="M5 12.5l4.2 4.2L19 7"/>`,
  plus: `<path d="M12 5v14M5 12h14"/>`,
  plate: `<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4"/><path d="M12 3.5v2M12 18.5v2M3.5 12h2M18.5 12h2"/>`,
  coffee: `<path d="M5 8h11v6.5A4.5 4.5 0 0 1 11.5 19h-2A4.5 4.5 0 0 1 5 14.5V8Z"/><path d="M16 10h1.5a2.5 2.5 0 0 1 0 5H16M8 4c-1-1 1-2 0-3M12 4c-1-1 1-2 0-3"/><path d="M4 21h14"/>`,
  family: `<path d="M3 11l9-7 9 7"/><path d="M5.5 10v9h13v-9"/><path d="M9.5 19v-5.5h5V19"/><path d="M12 12.4c-2-2.4-4-.5-2 1.2l2 2 2-2c2-1.7 0-3.6-2-1.2Z"/>`,
  kids: `<circle cx="9" cy="8" r="3"/><path d="M3 20v-2a5 5 0 0 1 10 0v2"/><circle cx="17" cy="10" r="2.2"/><path d="M14 20v-1.5a4 4 0 0 1 7 0V20"/>`,
  "fine-dine": `<path d="M4 15h16M5.5 15a6.5 6.5 0 0 1 13 0"/><path d="M12 5V3M9 7l-1.5-2M15 7l1.5-2"/><circle cx="12" cy="4" r="1"/>`,
  "cloud-kitchen": `<circle cx="6" cy="17" r="3"/><circle cx="18" cy="17" r="3"/><path d="M6 17h5l3-6h4M13 8h4l1 3M9 14h6"/><path d="M14 5h4l-2 4h-2"/>`,
  qsr: `<path d="M13 2 5 13h6l-1 9 9-12h-6V2Z"/><path d="M4 17h6M7 20h4"/>`,
  bar: `<path d="M4 4h16l-7 8v7M13 19h-4M9 15h6"/><path d="M7 7h10"/><circle cx="19" cy="3" r="1.5"/>`,
  stall: `<path d="M3 9h18l-2-5H5L3 9Z"/><path d="M5 9v11M19 9v11M3 20h18"/><path d="M7 9c0 3 2 4 2 4s2-1 2-4M13 9c0 3 2 4 2 4s2-1 2-4"/>`,
  "south-indian": `<path d="M4 13h16c0 5-3.5 8-8 8s-8-3-8-8Z"/><path d="M3 13h18"/><path d="M7 9c-2-2 2-3 0-5M12 9c-2-2 2-3 0-5M17 9c-2-2 2-3 0-5"/><circle cx="8" cy="17" r="1" fill="currentColor" stroke="none"/>`,
  biryani: `<path d="M4 11h16c0 5-3.5 8-8 8s-8-3-8-8Z"/><path d="M3 11h18"/><path d="M12 11V5c0-1.5 1-2 2-2.5M9 8c-1.5-1-1-3 1-3.5"/><path d="M7 15h10"/>`,
  bengali: `<path d="M4 12h16c0 5-3.5 9-8 9s-8-4-8-9Z"/><path d="M3 12h18"/><path d="M7 16c2 1.5 4 1.5 6 0s4-1.5 6 0"/><path d="M8 8c-2-2 2-3 0-5M14 8c-2-2 2-3 0-5"/>`,
  chaat: `<path d="M6 8h12l-1.5 9.5a3 3 0 0 1-3 2.5h-3a3 3 0 0 1-3-2.5Z"/><path d="M8 8l1.5-4M16 8l-1.5-4"/><path d="M9 12h6"/>`,
  tiffin: `<rect x="3" y="10" width="18" height="8" rx="2"/><path d="M8 10V7a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v3"/><path d="M3 14h18M9 18v2M15 18v2"/>`,
  seafood: `<path d="M4 12c3-4 8-6 12-4l4-2-1 5 1 5-4-2c-4 2-9 0-12-2Z"/><circle cx="9" cy="11" r="1" fill="currentColor" stroke="none"/><path d="M13 12c2 0 3 1 3 2"/>`,
  thai: `<path d="M4 12h16c0 5-3.5 8-8 8s-8-3-8-8Z"/><path d="M3 12h18"/><path d="M8 8c1-2 3-2 4 0M14 7c1-2 3-2 4 0"/><path d="M8 16h2M14 16h2"/>`,
  "other-asian": `<path d="M5 13h14c0 4-3 7-7 7s-7-3-7-7Z"/><path d="M4 13h16"/><path d="M6 8l4 3 3-4 3 4 2-2"/>`,
  arabian: `<path d="M4 13h16c0 5-3.5 8-8 8s-8-3-8-8Z"/><path d="M3 13h18"/><circle cx="12" cy="9" r="3"/><path d="M6 16h12"/>`,
  mexican: `<path d="M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16Z"/><path d="M12 4v16"/><circle cx="9" cy="9" r="1.6" fill="currentColor" stroke="none"/><path d="M12 20c3 0 5-2 5-5h-5Z" fill="currentColor" stroke="none" opacity=".5"/>`,
  african: `<path d="M4 13h16c0 5-3.5 8-8 8s-8-3-8-8Z"/><path d="M3 13h18"/><circle cx="12" cy="7" r="3"/><path d="M6 17c2 1 4 1 6 0s4-1 6 0"/>`,
  desserts: `<path d="M5 11h14l-1.5 8a2 2 0 0 1-2 1.5h-7a2 2 0 0 1-2-1.5Z"/><path d="M7 11l1-3M12 11V6M17 11l-1-3"/><circle cx="12" cy="4" r="1.4"/>`,
  canteen: `<path d="M4 9h16l-1 11H5Z"/><path d="M3 9h18"/><path d="M8 9V7a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M9 13h6"/>`,
  dhaba: `<path d="M3 11h18l-2-4H5Z"/><path d="M5 11v9M19 11v9M3 20h18"/><path d="M9 11v9M15 11v9"/>`,
  "street-stall": `<path d="M4 9h16l-1.5-4h-13Z"/><path d="M4 9v11M20 9v11"/><path d="M4 14h16"/><path d="M9 14v6M15 14v6"/><circle cx="12" cy="7" r="1.5"/>`,
  "hotel-restaurant": `<path d="M5 20V6a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v14"/><path d="M15 10h3a2 2 0 0 1 2 2v8"/><path d="M3 20h18"/><path d="M8 8h4M8 12h4M8 16h4"/>`,
  takeaway: `<path d="M6 8h12l-1 12H7Z"/><path d="M5 8h14"/><path d="M9 8V6a3 3 0 0 1 6 0v2"/><path d="M9 13h6"/>`,
  egg: `<path d="M12 4c3.5 0 6 4 6 7.5S15.5 20 12 20s-6-4.8-6-8.5S8.5 4 12 4Z"/><circle cx="10" cy="11" r="1.4" fill="currentColor" stroke="none"/>`,
  "gluten-free": `<path d="M4 14h16M4 18h16"/><path d="M8 4c4 2 4 6 0 8"/><path d="M14 6c3 2 3 6 0 8"/>`,
  "north-indian": `<path d="M4 12h16c0 5-3.5 9-8 9s-8-4-8-9Z"/><path d="M3 12h18"/><path d="M8 8c-2-2 2-3 0-5M14 8c-2-2 2-3 0-5"/><path d="M9 16h6"/>`,
  chinese: `<path d="M3 14c1-6 5-9 9-9s8 3 9 9c-5 2-13 2-18 0Z"/><path d="M7 12l3 2M12 9l2 3M17 11l-1 3"/><path d="M5 16c4 1.5 10 1.5 14 0"/>`,
  italian: `<path d="M4 19 9 5c5 1.5 8.5 5 11 10L4 19Z"/><path d="M5 18c5-3.5 9-5 14-5.5"/><circle cx="11" cy="11" r="1.2" fill="currentColor" stroke="none"/><circle cx="15" cy="15" r="1.2" fill="currentColor" stroke="none"/>`,
  continental: `<path d="M7 3v7M4 3v4c0 2 1.2 3 3 3s3-1 3-3V3M7 10v11M16 3v18M16 3c3 2 3 7 0 9"/>`,
  "street-food": `<path d="M3 14c1-6 5-9 9-9s8 3 9 9H3Z"/><path d="M3 14h18M6 17v3M18 17v3"/><path d="M7 11l3 2M13 10l2 2"/>`,
  multi: `<circle cx="12" cy="12" r="5"/><circle cx="12" cy="4" r="1.5"/><circle cx="12" cy="20" r="1.5"/><circle cx="4" cy="12" r="1.5"/><circle cx="20" cy="12" r="1.5"/>`,
  leaf: `<path d="M20 4C11 4 5 8 5 15c0 3 2 5 5 5 7 0 10-7 10-16Z"/><path d="M4 20c3-5 7-8 12-10"/>`,
  "non-veg": `<path d="M15 4c3 2 4 6 2 9-2 4-7 5-10 2-3-3-2-8 2-10 2-1 4-1 6-1Z"/><path d="m7 17-3 3M15 4l1-2"/>`,
  vegan: `<path d="M5 19C4 11 9 5 20 4c0 10-5 15-12 14"/><path d="M5 19c2-5 6-8 11-10"/><path d="M8 16c-3 0-4-2-4-4 3 0 4 2 4 4Z"/>`,
  jain: `<path d="M12 3c2 3 5 4 7 4-1 5-3 9-7 11-4-2-6-6-7-11 2 0 5-1 7-4Z"/><circle cx="12" cy="11" r="2.5"/><path d="M7 21h10"/>`,
  halal: `<path d="M15.5 3a8.5 8.5 0 1 0 4.5 12A7 7 0 1 1 15.5 3Z"/><path d="M17 7l2 2 2-2"/>`,
  date: `<path d="M4 5h16l-7 8v6M13 19h-4M9 13h6"/><path d="M18 3c2 0 3 2 3 3-2 0-3-1-3-3Z"/>`,
  solo: `<circle cx="12" cy="6" r="3"/><path d="M6 21v-4a6 6 0 0 1 12 0v4M9 21v-4a3 3 0 0 1 6 0v4"/>`,
  group: `<circle cx="8" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M2 20v-3a6 6 0 0 1 12 0v3M14 15a5 5 0 0 1 8 4v1"/>`,
  work: `<rect x="4" y="4" width="16" height="12" rx="2"/><path d="M2 20h20M9 16v1M15 16v1"/><path d="m9 9 2 2 4-4"/>`,
  "late-night": `<path d="M20 15.5A8.5 8.5 0 0 1 8.5 4 8.5 8.5 0 1 0 20 15.5Z"/><path d="M17 4h4l-4 4h4"/>`,
  outdoor: `<path d="M12 3v3M5 6h14l1 5H4Z"/><path d="M6 11v9M18 11v9M6 20h12"/><path d="M10 20v-5h4v5"/>`,
  spice: `<path d="M15 4c2 4 1 8-2 11L7 21c-1 1-3 0-3-1l6-6c3-3 6-4 5-10Z"/><path d="M15 4c2-2 4-2 5-2 0 2-1 4-3 5"/><path d="M9 15c2 0 4 1 4 3"/>`,
  comfort: `<path d="M4 13h16c0 5-3.5 8-8 8s-8-3-8-8Z"/><path d="M3 13h18"/><path d="M12 11c-2.5-2.5-5 .5 0 3 5-2.5 2.5-5.5 0-3Z"/>`,
  search: `<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5"/><path d="M8 10.5h5M10.5 8v5"/>`,
  pin: `<path d="M12 22s7-6.2 7-12a7 7 0 1 0-14 0c0 5.8 7 12 7 12Z"/><circle cx="12" cy="10" r="2.5"/>`,
  layers: `<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5M3 16l9 5 9-5"/>`,
  sun: `<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19"/>`,
  moon: `<path d="M20 15.5A8.5 8.5 0 0 1 8.5 4 8.5 8.5 0 1 0 20 15.5Z"/><path d="M17 4h4l-4 4h4"/>`,
  flame: `<path d="M13 2c1 4-2 5-2 8 0 2 1 3 2 3 2 0 3-2 2-4 3 2 5 5 5 8a8 8 0 0 1-16 0c0-5 4-8 5-12 1 3 3 3 4-3Z"/>`,
  bowl: `<path d="M3 11h18c0 6-4 10-9 10s-9-4-9-10Z"/><path d="M2 11h20M8 7c-2-2 2-3 0-5M14 7c-2-2 2-3 0-5"/>`,
  wrap: `<path d="M4 20 8 5l12 4-4 15-12-4Z"/><path d="M8 5c3 1 5 3 5 6s-1 6-1 8M4 20c4-2 8-2 12 4"/>`,
  glass: `<path d="M5 4h14l-6 8v7M13 19h-4M9 12h6"/><circle cx="18" cy="3" r="1.5"/>`,
  "quick-bite": `<circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2"/>`,
  "live-music": `<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>`,
  scooter: `<circle cx="5" cy="18" r="3"/><circle cx="19" cy="18" r="3"/><path d="M5 18h8l4-10h-4M13 8l4 10M9 18l3-7h5"/>`,
  "map-style": `<path d="M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3V6Z"/><path d="M9 3v15M15 6v15"/>`,
  budget: `<circle cx="12" cy="12" r="8.5"/><path d="M14.5 9.2a3 3 0 0 0-2.5-1.2c-1.4 0-2.5.8-2.5 2s1 1.7 2.5 2 2.5.8 2.5 2-1.1 2-2.5 2a3 3 0 0 1-2.5-1.2"/><path d="M12 6.5v11"/>`,
  location: `<circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="8"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2"/>`,
  pets: `<circle cx="7" cy="9" r="2.6"/><circle cx="17" cy="9" r="2.6"/><path d="M5 15c2 0 3 1.5 3 3M11 15c2 0 3 1.5 3 3"/><path d="M19 15c-2 0-3 1.5-3 3M15 15c-2 0-3 1.5-3 3"/>`,
  close: `<path d="M6 6l12 12M18 6L6 18"/>`,
  access: `<circle cx="12" cy="5" r="2"/><path d="M5 9h14M12 9v6l-2.5 6M12 15l3 6"/><circle cx="12" cy="9" r="2.5"/>`,
  blocked: `<circle cx="12" cy="12" r="8.5"/><path d="M6 6l12 12"/>`,
  seating: `<path d="M5 12V8a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v4"/><path d="M3 12h18v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/><path d="M6 18v3M18 18v3"/>`,
  bookmark: `<path d="M6.5 3.5h11a1 1 0 0 1 1 1v16l-6.5-4-6.5 4v-16a1 1 0 0 1 1-1Z"/>`,
  "bookmark-filled": `<path d="M6.5 3.5h11a1 1 0 0 1 1 1v16l-6.5-4-6.5 4v-16a1 1 0 0 1 1-1Z" fill="currentColor"/>`,
  walk: `<circle cx="13" cy="4.5" r="2"/><path d="m11 21 2-6-2.5-3 1-4.5L15 9l3 1"/><path d="M9.5 11.5 7 15H4"/>`,
  clock: `<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>`,
};

export default function InterfaceIcon({ name, size = 18, strokeWidth = 1.8, className = "" }) {
  const markup = ICONS[name] || ICONS.sparkles;
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={className}
      dangerouslySetInnerHTML={{ __html: markup }}
    />
  );
}
