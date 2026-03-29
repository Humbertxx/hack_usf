"use client";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

type InsightCardProps = {
  person: "grandma" | "grandpa";
  metric?: number;
  setmetric?: (value: number) => void;
};

export default function InsightCard({
  person,
  setmetric,
  metric,
}: InsightCardProps) {
  const chartDataMap: Record<number, unknown[]> = {
    1: [
      // Activity Data
      { name: "Mon", sales: 4500, profit: 30 },
      { name: "Tue", sales: 5200, profit: 45 },
      { name: "Wed", sales: 3100, profit: 15 },
      { name: "Thu", sales: 4800, profit: 35 },
      { name: "Fri", sales: 6000, profit: 60 },
      { name: "Sat", sales: 2000, profit: 10 },
      { name: "Sun", sales: 3500, profit: 25 },
    ],
    2: [
      // Sleep Data
      { name: "Mon", sales: 7, profit: 2 },
      { name: "Tue", sales: 6.5, profit: 1.5 },
      { name: "Wed", sales: 8, profit: 3 },
      { name: "Thu", sales: 7.2, profit: 2.2 },
      { name: "Fri", sales: 5.5, profit: 1 },
      { name: "Sat", sales: 9, profit: 4 },
      { name: "Sun", sales: 8.5, profit: 3.5 },
    ],
    3: [
      // Eating Data
      { name: "Mon", sales: 3, profit: 2 },
      { name: "Tue", sales: 2, profit: 4 },
      { name: "Wed", sales: 3, profit: 1 },
      { name: "Thu", sales: 3, profit: 2 },
      { name: "Fri", sales: 1, profit: 5 },
      { name: "Sat", sales: 2, profit: 3 },
      { name: "Sun", sales: 3, profit: 2 },
    ],
    4: [
      // Medical Data
      { name: "Mon", sales: 72, profit: 110 },
      { name: "Tue", sales: 75, profit: 115 },
      { name: "Wed", sales: 70, profit: 108 },
      { name: "Thu", sales: 82, profit: 125 },
      { name: "Fri", sales: 74, profit: 112 },
      { name: "Sat", sales: 68, profit: 105 },
      { name: "Sun", sales: 71, profit: 109 },
    ],
  };

  const titleData = {
    grandma: [
      {
        name: "Activity Level",
        measurement: "67 hrs/day",
        description: "More active than usual.",
      },

      {
        name: "Sleep Quality",
        measurement: "67%",
        description: "Less sleep than normal",
      },

      {
        name: "Meal Regularity",
        measurement: "100/100",
        description: "Well fed.",
      },

      {
        name: "Well-Being Score",
        measurement: "0/100",
        description: "Uh oh.",
      },
    ],
    grandpa: [
      {
        name: "Activity Level",
        measurement: "76 hrs/day",
        description: "More active than usual o.o.",
      },

      {
        name: "Sleep Quality",
        measurement: "67%",
        description: "More sleep than normal",
      },

      {
        name: "Meal Regularity",
        measurement: "89/100",
        description: "Quite well fed.",
      },

      {
        name: "Well-Being Score",
        measurement: "0/100",
        description: "yea.",
      },
    ],
  };

  return (
    <>
      <div className="flex flex-wrap justify-between items-center gap-5 w-[100%]">
        <div></div>
        {titleData[person].map((item, index) => (
          <button
            key={index}
            className={`flex flex-col p-5 items-start gap-5 justify-center shadow-lg 2xl:w-[320px] 2xl:h-[180px] md:w-[210px] md:h-[110px] rounded-2xl hover:shadow-2xl ${metric === index + 1 ? "bg-sky-200" : "bg-sky-50"}`}
            onClick={() => setmetric?.(index + 1)}
          >
            <p className="text-2xl">{item.measurement}</p>
            <p className="text-base text-gray-500">{item.description}</p>
          </button>
        ))}
        <div className="h-[400px] w-full">
          {/* ResponsiveContainer makes the chart fill its parent div */}
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartDataMap[metric || 1]}>
              {/* 1. The Grid */}
              <CartesianGrid strokeDasharray="3 3" />

              {/* 2. The Axes (dataKey must match your object keys) */}
              <XAxis dataKey="name" />
              <YAxis />

              {/* 3. The Interactivity */}
              <Tooltip />

              {/* 4. The Visuals */}
              <Line
                type="monotone"
                dataKey="sales"
                stroke="#8884d8"
                strokeWidth={2}
              />
              <Line type="monotone" dataKey="profit" stroke="#82ca9d" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </>
  );
}

// <div className="flex items-center justify-center gap-6 flex-wrap p-1 mt-5"> old top div
// <div className="flex flex-wrap gap-6">
