// Hi-fi icons — same set as mid-fi but designed for light bg, slightly thicker stroke.

function HFIcon({ d, size = 16, sw = 1.75 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" style={{flexShrink:0}}>
      {d}
    </svg>
  );
}

const HF_ICONS = {
  overview: <HFIcon d={<><rect x="2" y="2" width="5" height="5" rx="1"/><rect x="9" y="2" width="5" height="5" rx="1"/><rect x="2" y="9" width="5" height="5" rx="1"/><rect x="9" y="9" width="5" height="5" rx="1"/></>} />,
  runs:     <HFIcon d={<><path d="M4 3 L12 8 L4 13 Z"/></>} />,
  cron:     <HFIcon d={<><circle cx="8" cy="8" r="6"/><path d="M8 5 V8 L10 10"/></>} />,
  issues:   <HFIcon d={<><path d="M8 2 L14 13 L2 13 Z"/><path d="M8 6 V9 M8 11 V11.1"/></>} />,
  books:    <HFIcon d={<><path d="M3 3 H11 V13 H3 Z M3 3 Q2 3 2 4 V12 Q2 13 3 13"/><path d="M5 6 H9 M5 8 H9"/></>} />,
  urls:     <HFIcon d={<><path d="M6.5 9.5 L9.5 6.5 M6 6 L4 8 Q2 10 4 12 Q6 14 8 12 L10 10 M10 10 L12 8 Q14 6 12 4 Q10 2 8 4 L6 6"/></>} />,
  shops:    <HFIcon d={<><path d="M2 6 L3 3 H13 L14 6 M2 6 V13 H14 V6 M2 6 H14 M6 13 V9 H10 V13"/></>} />,
  prices:   <HFIcon d={<><path d="M8 2 V14 M11 4 H6.5 Q4.5 4 4.5 6 Q4.5 8 6.5 8 H9.5 Q11.5 8 11.5 10 Q11.5 12 9.5 12 H5"/></>} />,
  search:   <HFIcon d={<><circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5 L14 14"/></>} />,
  chevron:  <HFIcon d={<><path d="M5 3 L10 8 L5 13"/></>} />,
  chevronD: <HFIcon d={<><path d="M3 5 L8 10 L13 5"/></>} />,
  arrow:    <HFIcon d={<><path d="M3 8 H13 M9 4 L13 8 L9 12"/></>} />,
  external: <HFIcon d={<><path d="M6 3 H3 V13 H13 V10 M9 3 H13 V7 M13 3 L8 8"/></>} />,
  plus:     <HFIcon d={<><path d="M8 3 V13 M3 8 H13"/></>} />,
  refresh:  <HFIcon d={<><path d="M14 4 V8 H10"/><path d="M13.5 8 A5.5 5.5 0 1 1 12.5 4.5"/></>} />,
  filter:   <HFIcon d={<><path d="M2 3 H14 L10 8 V13 L6 11 V8 Z"/></>} />,
  dots:     <HFIcon d={<><circle cx="3" cy="8" r="1" fill="currentColor" stroke="none"/><circle cx="8" cy="8" r="1" fill="currentColor" stroke="none"/><circle cx="13" cy="8" r="1" fill="currentColor" stroke="none"/></>} />,
  download: <HFIcon d={<><path d="M8 2 V11 M4 7 L8 11 L12 7 M3 13 H13"/></>} />,
  stop:     <HFIcon d={<><rect x="4" y="4" width="8" height="8" rx="1"/></>} />,
  play:     <HFIcon d={<><path d="M5 3 L12 8 L5 13 Z"/></>} />,
  pause:    <HFIcon d={<><rect x="4" y="3" width="3" height="10" rx="0.5"/><rect x="9" y="3" width="3" height="10" rx="0.5"/></>} />,
  cycle:    <HFIcon d={<><path d="M14 4 V8 H10 M2 12 V8 H6"/><path d="M3 6 A5 5 0 0 1 12 5 M13 10 A5 5 0 0 1 4 11"/></>} />,
  settings: <HFIcon d={<><circle cx="8" cy="8" r="2"/><path d="M8 1 V3 M8 13 V15 M1 8 H3 M13 8 H15 M3 3 L4.5 4.5 M11.5 11.5 L13 13 M3 13 L4.5 11.5 M11.5 4.5 L13 3"/></>} />,
  check:    <HFIcon d={<><path d="M3 8 L7 12 L13 4"/></>} />,
  bang:     <HFIcon d={<><circle cx="8" cy="8" r="6"/><path d="M8 5 V9 M8 11 V11.1"/></>} />,
};

window.HFIcon = HFIcon;
window.HF_ICONS = HF_ICONS;
