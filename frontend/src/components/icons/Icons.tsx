// Line icons from the design reference's inline SVG sprite.
import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function Svg({ className, children, ...rest }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
      className={className ? `icon ${className}` : "icon"}
      {...rest}
    >
      {children}
    </svg>
  );
}

export const FolderIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 7.5a2 2 0 0 1 2-2h5l2.2 2.5H19a2 2 0 0 1 2 2V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
  </Svg>
);

export const PlusIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 4v16M4 12h16" />
  </Svg>
);

export const ArrowUpIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 20V5m0 0-6 6m6-6 6 6" />
  </Svg>
);

export const PaperclipIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="m8.5 12.5 5.7-5.7a3.6 3.6 0 0 1 5.1 5.1l-8.3 8.2a5.2 5.2 0 0 1-7.3-7.3l8.3-8.4a2.2 2.2 0 0 1 3.2 3.2l-8.1 8.2" />
  </Svg>
);

export const GearIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9.9 3.3h4.2l.5 2.1a7.8 7.8 0 0 1 1.6.9l2.1-.7 2.1 3.6-1.6 1.6a7.8 7.8 0 0 1 0 1.8l1.6 1.6-2.1 3.6-2.1-.7a7.8 7.8 0 0 1-1.6.9l-.5 2.1H9.9l-.5-2.1a7.8 7.8 0 0 1-1.6-.9l-2.1.7-2.1-3.6 1.6-1.6a7.8 7.8 0 0 1 0-1.8L3.6 9.2l2.1-3.6 2.1.7a7.8 7.8 0 0 1 1.6-.9z" />
    <circle cx="12" cy="12" r="3.1" />
  </Svg>
);

export const HelpIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M9.7 9.3a2.6 2.6 0 0 1 5.1.8c0 1.9-2.8 2.4-2.8 4.4M12 17.5v.3" />
  </Svg>
);

export const ShareIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="18" cy="5" r="3" />
    <circle cx="6" cy="12" r="3" />
    <circle cx="18" cy="19" r="3" />
    <path d="m8.7 10.6 6.6-4.2M8.7 13.4l6.6 4.2" />
  </Svg>
);

export const DotsIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="5" cy="12" r="1.4" fill="currentColor" stroke="none" />
    <circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" />
    <circle cx="19" cy="12" r="1.4" fill="currentColor" stroke="none" />
  </Svg>
);

export const ChevronDownIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="m6 9 6 6 6-6" />
  </Svg>
);

export const FileIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
    <path d="M14 3v5h5" />
  </Svg>
);

export const UploadIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 16V4m0 0-5 5m5-5 5 5M5 20h14" />
  </Svg>
);

export const CloseIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 6l12 12M18 6 6 18" />
  </Svg>
);
