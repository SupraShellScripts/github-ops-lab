// Original non-board-specific synthetic oscillator/counter. No pin locations.
module synthetic_top #(parameter integer TAP = 24)(
    input wire clk,
    input wire reset_n,
    output wire led
);
  reg [24:0] counter;
  always @(posedge clk or negedge reset_n)
    if (!reset_n) counter <= 25'd0;
    else counter <= counter + 25'd1;
  assign led = counter[TAP];
endmodule
