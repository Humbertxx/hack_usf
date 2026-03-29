"use client";


export default function InsightCard() {
  const titleData = [
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
  ];




  return (
    <>

    <div className ="flex flex-wrap gap-6">
        {titleData.map((item,index) => (
            <div key={index} className="shadow-lg 2xl:w-[820px] 2xl:h-[360px] md:w-[410px] md:h-[180px] bg-white rounded-2xl hover:shadow-2xl">
                <p className="ml-6 mt-6 font-bold text-xl">{item.name}</p>
                <p className="ml-6 mt-8 text-2xl">{item.measurement}</p>
                <p className="ml-6 mt-8 text-base text-gray-500">{item.description}</p>
            </div>  
        ))}
    </div>


    </>
  );
}

// <div className="flex items-center justify-center gap-6 flex-wrap p-1 mt-5"> old top div




    /*
      <div className="shadow-lg w-[410px] h-[180px] bg-white rounded-2xl hover:shadow-2xl">
        <p className="ml-6 mt-6 font-bold text-xl">Activity Level</p>
        <p className="ml-6 mt-8 text-2xl">67 hrs/day</p>
        <p className="ml-6 mt-8 text-base text-gray-500">
          More active than usual.
        </p>
      </div>

      <div className="shadow-lg w-[410px] h-[180px] bg-white rounded-2xl hover:shadow-2xl">
        <p className="ml-6 mt-6 font-bold text-xl">Sleep Quality</p>
        <p className="ml-6 mt-8 text-2xl">67%</p>
        <p className="ml-6 mt-8 text-base text-gray-500">
          Less sleep than normal.
        </p>
      </div>

      <div className="shadow-lg w-[410px] h-[180px] bg-white rounded-2xl hover:shadow-2xl">
        <p className="ml-6 mt-6 font-bold text-xl">Meal Regularity</p>
        <p className="ml-6 mt-8 text-2xl">100%</p>
        <p className="ml-6 mt-8 text-base text-gray-500">Well fed.</p>
      </div>

      <div className="shadow-lg w-[410px] h-[180px] bg-white rounded-2xl hover:shadow-2xl">
        <p className="ml-6 mt-6 font-bold text-xl">Well-being Score</p>
        <p className="ml-6 mt-8 text-2xl">0/100</p>
        <p className="ml-6 mt-8 text-base text-gray-500">Uh oh.</p>
      </div>
      */