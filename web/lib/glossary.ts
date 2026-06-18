/**
 * Plain-language definitions for the handful of technical words kept on the main site (everything
 * deeper lives on the deep-dive page). Written for someone who isn't an engineer: short, concrete,
 * no jargon explaining the jargon. <Term name="..."> looks these up so a word means the same thing
 * everywhere it appears.
 */
export const GLOSSARY: Record<string, string> = {
  embedding:
    "A song boiled down to a list of numbers that captures how it sounds. Two songs that sound alike end up with similar numbers, so a computer can measure how close they are.",
  clap:
    "The model that does the listening. It plays a track and turns the sound into one of those number-lists. It was trained on a huge pile of music.",
  cosine:
    "A closeness score from 0 to 1 for how alike two songs sound. The nearer to 1, the more they have in common.",
  rrf:
    "Reciprocal-rank fusion. A fair way to merge two ranked lists: a song's score comes from where it sits on each list, not from raw numbers, so neither source can drown out the other.",
  llm:
    "A large language model, the kind behind chatbots. Here it only writes the short note for each pick. It never decides the ranking.",
  consensus:
    "How strongly the music sources agree that two songs belong together. More agreement, higher score.",
  corpus:
    "The library of songs Doppel has already listened to and saved, so it doesn't have to listen again next time.",
  backfill:
    "When Doppel can't get audio for a song, it still keeps the picks the music sources strongly agree on. Those just don't get a sound score.",
  vibe:
    "Add a few words about the mood you want, like \"late-night drive,\" and Doppel leans the results that way.",
  musicbrainz: "An open encyclopedia of music: which song is which, who made it, and how they connect.",
  deezer:
    "A streaming service. Doppel listens to its 30-second previews and links out to it so you can play the full song.",
  scrobble:
    "Listening data from millions of people, which is how Doppel knows which songs tend to be played together.",
};
