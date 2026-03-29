"use client";

import Image from "next/image";
import { use, useState } from "react";

export default function Home() {
  interface basicstatus {
    type: string;
    text: string;
    time: string;
  }

  const values: basicstatus[] = [
    { type: "Waking hours", text: "SLept well", time: "6:20am" },
    { type: "Coffee?", text: "Iced", time: "6:30am" },
    { type: "Brushin", text: "Teeth nice and clean", time: "6:40am" },
    { type: "Cruisin", text: "Granny has a nice car", time: "6:50am" },
  ];

  //0 for today, 1 for yesterday, 2 for last week
  const [time, settime] = useState(0);
  const [grandma, setgrandma] = useState(true);
  const [grandpa, setgrandpa] = useState(false);

  return (
    <>
      <div className="p-10 w-full h-full flex flex-col gap-5 items-center justify-start">
        <div className="flex flex-col gap-3 justify-center w-[90%] md:w-[80%]">
          <p className="font-bold text-3xl">Activity Timeline</p>
          <p className="font-thin text-gray-600 text-sm">
            Here is whats happening with today!
          </p>
        </div>
        <div className="flex items-center justify-between w-[90%] md:w-[80%]">
          <div className="shadow flex justify-center items-center bg-sky-50 rounded-2xl w-[300px] h-[50px]">
            <button
              onClick={time === 0 ? () => settime(-1) : () => settime(0)}
              className={`hover:shadow bg-sky-50 w-[34%] h-full rounded-l-2xl hover:scale-110 transition duration-100 ease-in ${time === 0 ? "bg-sky-200" : ""}`}
            >
              today
            </button>
            <button
              onClick={time === 1 ? () => settime(-1) : () => settime(1)}
              className={`hover:shadow bg-sky-50 w-[34%] h-full hover:scale-110 transition duration-100 ease-in ${time === 1 ? "bg-sky-200" : ""}`}
            >
              yesterday
            </button>
            <button
              onClick={time === 2 ? () => settime(-1) : () => settime(2)}
              className={`hover:shadow bg-sky-50 w-[34%] h-full rounded-r-2xl hover:scale-110 transition duration-100 ease-in ${time === 2 ? "bg-sky-200" : ""}`}
            >
              last week
            </button>
          </div>
          <div className="shadow flex justify-center items-center bg-sky-50 rounded-2xl w-[300px] h-[50px]">
            <button
              onClick={() => setgrandma(!grandma)}
              className={`hover:shadow bg-sky-50 w-[50%] h-full rounded-l-2xl hover:scale-110 transition duration-100 ease-in ${grandma ? "bg-sky-200" : ""}`}
            >
              grandma
            </button>
            <button
              onClick={() => setgrandpa(!grandpa)}
              className={`hover:shadow bg-sky-50 w-[50%] h-full rounded-r-2xl hover:scale-110 transition duration-100 ease-in ${grandpa ? "bg-sky-200" : ""}`}
            >
              grandpa
            </button>
          </div>
        </div>
        <div className="flex flex-col gap-5 flex-wrap items-center justify-between w-[90%] md:w-[80%]">
          {values.map((item, index) => (
            <div
              key={index}
              className="w-full flex items-center justify-start gap-5"
            >
              <div className="flex items-center justify-start flex-col">
                <div className="rounded-full bg-green-500 h-12 w-12" />
                <div className="absolute w-[2px] bg-green-500 h-[100px]" />
              </div>
              <div className="shadow hover:shadow-xl transition duration-100 ease-in p-3 flex flex-col items-start justify-start bg-sky-50 w-full h-[75px] rounded-2xl">
                <div className="w-full flex justify-between">
                  <p className="font-bold text-xl">{item.type}</p>
                  <p className="light text-xs text-gray-600">{item.time}</p>
                </div>
                <p className="text-sm">{item.text}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
