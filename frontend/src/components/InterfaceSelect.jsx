import { useEffect, useId, useMemo, useRef, useState } from "react";
import InterfaceIcon from "./InterfaceIcon";

export default function SelectMenu({
  label,
  value,
  placeholder,
  options,
  onChange,
  disabled = false,
  searchable = false,
}) {
  const listboxId = useId();
  const rootRef = useRef(null);
  const triggerRef = useRef(null);
  const searchRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const selectedIndex = Math.max(0, options.findIndex((option) => option.value === value));
  const [highlightedIndex, setHighlightedIndex] = useState(selectedIndex);
  const selectedOption = options[selectedIndex];

  const filtered = useMemo(() => {
    if (!searchable || !query.trim()) return options;
    const needle = query.trim().toLowerCase();
    return options.filter(
      (option) =>
        option.label.toLowerCase().includes(needle) || option.value.toLowerCase().includes(needle),
    );
  }, [options, query, searchable]);

  useEffect(() => {
    if (!open) return undefined;
    const closeOnOutside = (event) => {
      if (!rootRef.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutside);
    return () => document.removeEventListener("pointerdown", closeOnOutside);
  }, [open]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  useEffect(() => {
    if (open && searchable) searchRef.current?.focus();
  }, [open, searchable]);

  // -1 represents the "any" entry rendered above the real options.
  const optionCycle = [-1, ...filtered.map((option, index) => index)];
  const clampOption = (index) => {
    if (index <= -1) return index === -1 ? -1 : Math.max(0, filtered.length - 1);
    return Math.max(0, index) % Math.max(1, filtered.length);
  };

  const openAt = (index) => {
    setHighlightedIndex(clampOption(index));
    setOpen(true);
  };

  const moveHighlight = (direction) => {
    const position = optionCycle.indexOf(highlightedIndex);
    const safePosition = position === -1 ? 0 : position;
    const next =
      (safePosition + direction + optionCycle.length) % optionCycle.length;
    setHighlightedIndex(optionCycle[next]);
  };

  const choose = (index) => {
    const option = filtered[index];
    if (index !== -1 && !option) return;
    onChange(option?.value || "");
    setQuery("");
    setOpen(false);
    triggerRef.current?.focus();
  };

  const handleKeyDown = (event) => {
    if (disabled) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (open) moveHighlight(1);
      else openAt(value ? selectedIndex + 1 : 0);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (open) moveHighlight(-1);
      else openAt(value ? selectedIndex - 1 : -1);
    } else if (event.key === "Home" && open) {
      event.preventDefault();
      setHighlightedIndex(0);
    } else if (event.key === "End" && open) {
      event.preventDefault();
      setHighlightedIndex(Math.max(0, filtered.length - 1));
    } else if (event.key === "Enter" || event.key === " ") {
      // Let the search field receive printable input instead of committing.
      if (event.target instanceof HTMLInputElement) return;
      event.preventDefault();
      if (open) choose(highlightedIndex);
      else openAt(value ? selectedIndex : -1);
    } else if (event.key === "Escape" && open) {
      event.preventDefault();
      setQuery("");
      setOpen(false);
    } else if (event.key === "Tab" && open) {
      setOpen(false);
    }
  };

  return (
    <div
      ref={rootRef}
      className={`select-menu ${open ? "is-open" : ""} ${disabled ? "is-disabled" : ""}`}
    >
      <span className="select-menu__label">{label}</span>
      <button
        ref={triggerRef}
        type="button"
        className="select-menu__trigger"
        role="combobox"
        aria-controls={listboxId}
        aria-label={label}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-activedescendant={
          open
            ? highlightedIndex < 0
              ? `${listboxId}clear`
              : `${listboxId}opt-${highlightedIndex}`
            : undefined
        }
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : openAt(value ? selectedIndex : -1))}
        onKeyDown={handleKeyDown}
      >
        <span className="select-menu__value">
          {value ? (
            <>
              <span className="select-menu__value-icon">
                <InterfaceIcon name={selectedOption?.icon} size={18} />
              </span>
              <span>{selectedOption?.label}</span>
            </>
          ) : (
            <>
              <span className="select-menu__value-icon select-menu__value-icon--any">
                <InterfaceIcon name="sparkles" size={18} />
              </span>
              <span>{placeholder}</span>
            </>
          )}
        </span>
        <span className="select-menu__chevron">
          <InterfaceIcon name="chevron-down" size={17} strokeWidth={2.2} />
        </span>
      </button>

      {open && (
        <div className="select-menu__listbox" id={listboxId} role="listbox" aria-label={label}>
          <div className="select-menu__listhead">
            <span>{label}</span>
            <small>{searchable ? `${filtered.length}/${options.length}` : `${options.length}`} options</small>
          </div>
          {searchable && (
            <div className="select-menu__search">
              <InterfaceIcon name="search" size={15} />
              <input
                ref={searchRef}
                type="text"
                value={query}
                placeholder={`Search ${label.toLowerCase()}…`}
                aria-label={`Search ${label} options`}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setHighlightedIndex(-1);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Escape") {
                    event.stopPropagation();
                    if (query) setQuery("");
                    else setOpen(false);
                  }
                }}
              />
            </div>
          )}
          <div
            id={`${listboxId}clear`}
            role="option"
            aria-selected={!value}
            className={`select-menu__option select-menu__option--clear ${!value ? "is-selected" : ""} ${highlightedIndex === -1 ? "is-highlighted" : ""}`}
            onMouseEnter={() => setHighlightedIndex(-1)}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => choose(-1)}
          >
            <span className="select-menu__option-icon">
              <InterfaceIcon name="sparkles" size={19} />
            </span>
            <span className="select-menu__option-label">{placeholder}</span>
            {!value && (
              <span className="select-menu__check">
                <InterfaceIcon name="check" size={16} strokeWidth={2.4} />
              </span>
            )}
          </div>
          {filtered.map((option, index) => {
            const isSelected = option.value === value;
            const isHighlighted = index === highlightedIndex;
            // A count of zero means this filter would return an empty page. It
            // stays selectable — the vocabulary is canonical and a reader may be
            // looking for the gap itself — but it is marked, so the number is
            // visible before the click rather than after it.
            const isEmpty = option.count === 0;
            return (
              <div
                key={option.key ?? option.value}
                id={`${listboxId}opt-${index}`}
                role="option"
                aria-selected={isSelected}
                aria-disabled={isEmpty || undefined}
                className={`select-menu__option ${isHighlighted ? "is-highlighted" : ""} ${isSelected ? "is-selected" : ""} ${isEmpty ? "is-empty" : ""}`}
                onMouseEnter={() => setHighlightedIndex(index)}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(index)}
              >
                <span className="select-menu__option-icon">
                  <InterfaceIcon name={option.icon} size={19} />
                </span>
                <span className="select-menu__option-label">{option.label}</span>
                {option.count != null && (
                  <span
                    className="select-menu__count"
                    title={
                      isEmpty
                        ? "No place in the loaded city has this yet"
                        : `${option.count.toLocaleString("en-IN")} places in the loaded city`
                    }
                  >
                    {isEmpty ? "none yet" : option.count.toLocaleString("en-IN")}
                  </span>
                )}
                {isSelected && (
                  <span className="select-menu__check">
                    <InterfaceIcon name="check" size={16} strokeWidth={2.4} />
                  </span>
                )}
              </div>
            );
          })}
          {filtered.length === 0 && (
            <p className="select-menu__none">No option matches “{query.trim()}”</p>
          )}
        </div>
      )}
    </div>
  );
}
