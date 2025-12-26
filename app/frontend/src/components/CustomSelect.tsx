import React from "react";

export interface CustomSelectOption {
  value: string;
  label: string; // Shown in dropdown
  selectedLabel: string; // Shown when selected
}

interface CustomSelectProps {
  value: string;
  onChange: (e: React.ChangeEvent<HTMLSelectElement>) => void;
  options: CustomSelectOption[];
  className?: string;
  selectClassName?: string;
  disabled?: boolean;
  width: string;
}

const CustomSelect: React.FC<CustomSelectProps> = ({
  value,
  onChange,
  options,
  width,
  className = "",
  selectClassName = "",
  disabled = false,
}) => {
  const selectedOption = options.find(opt => opt.value === value);

  return (
    <div className={`custom-select-wrapper ${className}`} style={{ position: "relative" }}>
      <select
        className={`custom-select ${selectClassName}`}
        value={value}
        onChange={onChange}
        disabled={disabled}
        style={{width: width}}
      >
        {options.map(opt => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      <div
        className="custom-select-overlay"
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          right: 0,
          bottom: "1px",
          pointerEvents: "none",
          display: "flex",
          alignItems: "center",
          paddingLeft: 8,
          backgroundColor: "#fff",
          color: disabled ? "#aaa" : undefined,
        }}
      >
        {selectedOption ? selectedOption.selectedLabel : ""}
      </div>
    </div>
  );
};

export default CustomSelect;
