import Link from "next/link";

export default function NavBar() {
  return (
    <>
      <nav className="w-[100%] py-4 bg-white shadow-lg flex items-center justify-center max-md:gap-5 md:justify-around">
        <div className="font-bold text-2xl">Hows Grandma?</div>
        <div className="flex justify-around items-center justify-center gap-10">
          <Link
            className="bg-green-100 p-2 rounded hover:scale-110 transition duration-100 ease-in"
            href="/dashboard"
          >
            Home
          </Link>

          <Link
            className="bg-green-100 p-2 rounded hover:scale-110 transition duration-100 ease-in"
            href="/timeline"
          >
            Timeline
          </Link>

          <Link
            className="bg-green-100 p-2 rounded hover:scale-110 transition duration-100 ease-in"
            href="/insights"
          >
            Insights
          </Link>
        </div>
      </nav>
    </>
  );
}
