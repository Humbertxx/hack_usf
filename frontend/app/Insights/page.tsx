"use client";
import InsightCard from "../components/InsightCard";
import { useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

export default function Home() {
  const [grandma, setGrandma] = useState(true);
  const [grandpa, setGrandpa] = useState(false);
  const [grandmametric, setGrandmametric] = useState(0);
  const [grandpametric, setGrandpametric] = useState(0);

  return (
    <>
      <div className="p-10 w-full min-h-screen flex flex-col gap-10 items-center justify-start">
        <div className="flex justify-between w-[90%] md:w-[80%]">
          <div className="flex flex-col gap-3">
            <h1 className="m-0 text-3xl font-bold text-black">
              Health Insights
            </h1>
            <p className="mt-0 text-sm text-gray-600">
              AI-powered analysis of weekly pattern and trends
            </p>
          </div>

          <div className="flex gap-0 w-[200px] h-[50px] rounded-2xl border-0 bg-gray-200 justify-center">
            <button
              onClick={() => {
                setGrandma(!grandma);
              }}
              className={`hover:shadow w-[50%] h-full hover:scale-110 rounded-tl-2xl rounded-bl-2xl transition duration-100 ease-in ${grandma ? "bg-sky-200" : "bg-gray-200"}`}
            >
              grandma
            </button>

            <button
              onClick={() => {
                setGrandpa(!grandpa);
              }}
              className={`hover:shadow w-[50%] h-full hover:scale-110 rounded-tr-2xl rounded-br-2xl transition duration-100 ease-in ${grandpa ? "bg-sky-200" : "bg-gray-200"}`}
            >
              grandpa
            </button>
          </div>
        </div>
        {grandma && (
          <>
            <div className="flex flex-col w-[90%] md:w-[80%] ">
              <h2 className="text-2xl font-bold">Grandma</h2>
              <InsightCard
                person="grandma"
                metric={grandmametric}
                setmetric={setGrandmametric}
              />
            </div>
          </>
        )}
        {grandpa && (
          <>
            <div className="flex flex-col w-[90%] md:w-[80%] ">
              <h2 className="text-2xl font-bold">Grandpa</h2>
              <div className="flex flex-wrap justify-between items-center gap-5 w-[100%]">
                <InsightCard
                  person="grandpa"
                  metric={grandpametric}
                  setmetric={setGrandpametric}
                />
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}

/*
            className={`w-[200px] h-[50px] rounded-lg transition duration-100 border-0 ease-in
              ${grandma ? "bg-sky-200 shadow scale-105" : "bg-sky-50"}
              `}
*/
