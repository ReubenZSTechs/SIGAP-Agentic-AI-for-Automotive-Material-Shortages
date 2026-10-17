// Ikon garis 24px, tanpa dependensi. Pakai: <Icon name="plus" className="h-4 w-4" />
const P = {
  plus: 'M12 5v14M5 12h14', x: 'M6 6l12 12M18 6L6 18', check: 'M5 12.5l4.5 4.5L19 7',
  search: 'M11 4a7 7 0 100 14 7 7 0 000-14zM20 20l-4-4', menu: 'M4 7h16M4 12h16M4 17h16',
  chevronRight: 'M9 6l6 6-6 6', chevronDown: 'M6 9l6 6 6-6', arrowRight: 'M5 12h14M13 6l6 6-6 6',
  alert: 'M12 4l9 16H3L12 4zM12 10v4M12 17.5v.01', info: 'M12 21a9 9 0 100-18 9 9 0 000 18zM12 11v5M12 8v.01',
  edit: 'M4 20h4L19 9l-4-4L4 16v4zM13.5 6.5l4 4', trash: 'M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13M10 11v6M14 11v6',
  spark: 'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3zM19 16l.7 1.8 1.8.7-1.8.7L19 21l-.7-1.8-1.8-.7 1.8-.7L19 16z',
  box: 'M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3zM4 7.5l8 4.5 8-4.5M12 12v9', layers: 'M12 4l9 5-9 5-9-5 9-5zM3 14l9 5 9-5',
  truck: 'M3 6h11v10H3zM14 10h4l3 3v3h-7M5.2 18.5a1.8 1.8 0 103.6 0 1.8 1.8 0 00-3.6 0zM15.2 18.5a1.8 1.8 0 103.6 0 1.8 1.8 0 00-3.6 0z',
  warehouse: 'M3 10l9-6 9 6v10H3V10zM8 20v-6h8v6', tree: 'M5 4h6v4H5zM13 10h6v4h-6zM13 16h6v4h-6zM8 8v10h5M8 12h5',
  calendar: 'M4 6h16v14H4zM4 10h16M8 3v4M16 3v4', file: 'M7 3h8l4 4v14H7zM15 3v4h4M10 12h6M10 16h6',
  arrowLeft: 'M19 12H5M11 6l-6 6 6 6', filter: 'M4 5h16l-6 8v6l-4-2v-4L4 5z', panelLeft: 'M4 5h16v14H4zM9 5v14', play: 'M7 5l12 7-12 7V5z', send: 'M20 4L4 11l6 2 2 6 8-15z',
  clip: 'M21 11.5l-8.6 8.6a5 5 0 01-7-7l9-9a3.3 3.3 0 014.7 4.7l-9 9a1.7 1.7 0 01-2.4-2.4l8.3-8.3',
};
export default function Icon({ name, className = 'h-4 w-4' }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round"
         strokeLinejoin="round" className={`shrink-0 ${className}`} aria-hidden="true"><path d={P[name]} /></svg>
  );
}
