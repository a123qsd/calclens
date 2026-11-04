import type { SVGProps } from 'react';

type Props = SVGProps<SVGSVGElement>;
const Svg = ({ children, ...props }: Props) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{children}</svg>;

export const Aperture = (p: Props) => <Svg {...p}><circle cx="12" cy="12" r="9.5"/><path d="m7.4 3.9 4.8 8.1M3 10.5h9.2m7.6-5-7.6 6.5m8.6 6.1L12.2 12m-3.9 9.2 3.9-9.2"/></Svg>;
export const Home = (p: Props) => <Svg {...p}><path d="m3 11 9-8 9 8"/><path d="M5.5 9.5V21h13V9.5M9.5 21v-7h5v7"/></Svg>;
export const Compare = (p: Props) => <Svg {...p}><path d="M8 4 4 20M16 4l4 16M3 9h18M2 20h5m10 0h5"/><path d="M3 9c0 3 1 5 3 5s3-2 3-5m6 0c0 3 1 5 3 5s3-2 3-5"/></Svg>;
export const CheckSquare = (p: Props) => <Svg {...p}><rect x="3" y="3" width="18" height="18" rx="2"/><path d="m7.5 12 3 3 6-7"/></Svg>;
export const Book = (p: Props) => <Svg {...p}><path d="M4 4.5c3-1 5.6-.5 8 1.5v15c-2.4-2-5-2.5-8-1.5zm16 0c-3-1-5.6-.5-8 1.5v15c2.4-2 5-2.5 8-1.5z"/></Svg>;
export const Flask = (p: Props) => <Svg {...p}><path d="M9 3h6M10 3v6L4.5 19a1.3 1.3 0 0 0 1.1 2h12.8a1.3 1.3 0 0 0 1.1-2L14 9V3"/><path d="M7.5 15h9"/></Svg>;
export const Upload = (p: Props) => <Svg {...p}><path d="M12 16V3m0 0L7 8m5-5 5 5"/><path d="M4 14v6h16v-6"/></Svg>;
export const Download = (p: Props) => <Svg {...p}><path d="M12 3v13m0 0 5-5m-5 5-5-5"/><path d="M4 20h16"/></Svg>;
export const Play = (p: Props) => <Svg {...p}><path fill="currentColor" stroke="none" d="m8 5 11 7-11 7z"/></Svg>;
export const Info = (p: Props) => <Svg {...p}><circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/></Svg>;
export const Check = (p: Props) => <Svg {...p}><path d="m5 12 4.5 4.5L19 7"/></Svg>;
export const External = (p: Props) => <Svg {...p}><path d="M14 4h6v6m0-6-9 9"/><path d="M19 13v7H4V5h7"/></Svg>;
export const Sliders = (p: Props) => <Svg {...p}><path d="M4 6h16M4 18h16M8 3v6m8 6v6"/></Svg>;
export const Ruler = (p: Props) => <Svg {...p}><path d="m5 19 14-14 2 2L7 21z"/><path d="m15 7 2 2m-5 1 2 2m-5 1 2 2m-5 1 2 2"/></Svg>;
export const Trash = (p: Props) => <Svg {...p}><path d="M4 7h16m-10-4h4l1 4H9zM6 7l1 14h10l1-14M10 11v6m4-6v6"/></Svg>;
export const GitHub = (p: Props) => <Svg {...p}><path d="M15 22v-4c.1-1-.4-2-1-2.5 3 0 6-1.5 6-6A4.6 4.6 0 0 0 19 6c.3-1 .3-2 0-3 0 0-1 0-3 1.5a12 12 0 0 0-8 0C6 3 5 3 5 3c-.3 1-.3 2 0 3a4.6 4.6 0 0 0-1 3.5c0 4.5 3 6 6 6-.5.4-.8 1-1 1.5-2 .9-3-1-3-1-.5-1-1.5-1.5-1.5-1.5M9 22v-5"/></Svg>;
