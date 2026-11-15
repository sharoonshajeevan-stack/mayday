// src/components/hud/Calendar.jsx
//
// Small MAYDAY-styled month calendar shown on the left side of the HUD.

import { useMemo } from "react";

import "./Calendar.css";

const WEEKDAYS = ["S", "M", "T", "W", "T", "F", "S"];

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

export default function Calendar() {
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth();
  const today = now.getDate();

  const cells = useMemo(() => {
    const firstWeekday = new Date(year, month, 1).getDay();
    const daysInMonth = new Date(year, month + 1, 0).getDate();

    const list = [];

    for (let i = 0; i < firstWeekday; i += 1) {
      list.push(null);
    }

    for (let day = 1; day <= daysInMonth; day += 1) {
      list.push(day);
    }

    return list;
  }, [year, month]);

  return (
    <div className="mayday-calendar">
      <div className="calendar-header">
        <span className="calendar-indicator" />

        <span>CALENDAR</span>
      </div>

      <div className="calendar-month">
        {MONTHS[month]}

        <span className="calendar-year">{year}</span>
      </div>

      <div className="calendar-weekdays">
        {WEEKDAYS.map((day, index) => (
          <span key={`weekday-${index}`}>{day}</span>
        ))}
      </div>

      <div className="calendar-grid">
        {cells.map((day, index) => (
          <span
            key={`day-${index}`}
            className={
              day === today
                ? "calendar-day calendar-today"
                : "calendar-day"
            }
          >
            {day || ""}
          </span>
        ))}
      </div>
    </div>
  );
}
