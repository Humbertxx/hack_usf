"use client";

type InsightCardProps = {
  person: "grandma" | "grandpa";
};

export default function InsightCard({ person }: InsightCardProps) {
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
      {titleData[person].map((item, index) => (
        <div
          key={index}
          className="flex flex-col p-5 items-start gap-5 justify-center shadow-lg 2xl:w-[620px] 2xl:h-[360px] md:w-[410px] md:h-[180px] bg-white rounded-2xl hover:shadow-2xl"
        >
          <p className="font-bold text-xl">{item.name}</p>
          <p className="text-2xl">{item.measurement}</p>
          <p className="text-base text-gray-500">{item.description}</p>
        </div>
      ))}
    </>
  );
}

// <div className="flex items-center justify-center gap-6 flex-wrap p-1 mt-5"> old top div
// <div className="flex flex-wrap gap-6">
