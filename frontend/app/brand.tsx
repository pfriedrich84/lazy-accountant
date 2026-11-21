import { Box } from "@mui/material";
import logoUrl from "./assets/lazy-accountant-logo.svg?url";
import iconUrl from "./assets/lazy-accountant-icon.svg?url";

/** The same approved SVG assets are used by the app and the product README. */
export function Brand({ width = 192 }: { width?: number }) {
  return (
    <Box
      component="img"
      src={logoUrl}
      alt="Lazy Accountant"
      width={760}
      height={224}
      sx={{ display: "block", width, maxWidth: "100%", height: "auto" }}
    />
  );
}

export function BrandIcon() {
  return (
    <Box
      component="img"
      src={iconUrl}
      alt="Lazy Accountant"
      width={32}
      height={32}
      sx={{ display: { xs: "block", md: "none" }, flexShrink: 0 }}
    />
  );
}
